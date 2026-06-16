#!/usr/bin/env python3
"""Offline tests for the Nexus Q audio diagnostic analyzers."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
from contextlib import redirect_stdout
from typing import Any


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def load_tool(name: str, relpath: str) -> Any:
    path = os.path.join(ROOT, relpath)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


analyzer = load_tool("analyze_audio_probe_capture", "tools/analyze_audio_probe_capture.py")
summarizer = load_tool("summarize_audio_probe_runs", "tools/summarize_audio_probe_runs.py")
triage_tool = load_tool("triage_audio_sweep", "tools/triage_audio_sweep.py")


GOOD_METRICS = {
    "rms": 0.05,
    "expected_tone_rms": 0.04,
    "zero_cross_freq_hz": 440.4,
    "zero_cross_freq_error_pct": 0.09,
    "envelope_cv_25ms": 0.08,
    "envelope_low_pct_25ms": 0.0,
    "envelope_peak_to_trough_db_25ms": 1.5,
    "harmonic_power_ratio_2_8": 0.02,
    "clipped_pct": 0.0,
}


BAD_BASELINE = {
    "envelope_cv_25ms": 0.6324082274704905,
}


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def write_json(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def assert_signal_metrics() -> None:
    metrics = analyzer.self_test(440.0)
    sine = metrics["sine"]
    square = metrics["square"]
    flutter = metrics["flutter"]

    assert sine["envelope_cv_25ms"] < 0.01, sine
    assert sine["envelope_low_pct_25ms"] == 0.0, sine
    assert sine["envelope_peak_to_trough_db_25ms"] < 1.0, sine
    assert sine["envelope_mod_peak_hz_25ms"] == 0.0, sine
    assert sine["envelope_mod_peak_score_25ms"] < 0.2, sine
    assert sine["harmonic_power_ratio_2_8"] < 1e-6, sine
    assert 0.13 < sine["expected_tone_rms"] < 0.15, sine

    assert square["envelope_cv_25ms"] < 0.01, square
    assert square["envelope_mod_peak_hz_25ms"] == 0.0, square
    assert square["harmonic_power_ratio_2_8"] > 0.1, square

    assert flutter["envelope_cv_25ms"] > 0.4, flutter
    assert flutter["envelope_low_pct_25ms"] > 20.0, flutter
    assert flutter["envelope_peak_to_trough_db_25ms"] > 10.0, flutter
    assert 8.5 < flutter["envelope_mod_peak_hz_25ms"] < 9.5, flutter
    assert flutter["envelope_mod_peak_score_25ms"] > 0.6, flutter

    silence = analyzer.analyze_samples([0.0] * 48000, 48000, 440.0)
    assert silence["rms"] == 0.0, silence
    assert silence["rms_dbfs"] == -120.0, silence
    assert silence["expected_tone_rms"] == 0.0, silence


def add_run(root: str, name: str, status: str, metrics: dict[str, Any]) -> str:
    path = os.path.join(root, name)
    os.makedirs(path)
    if status.startswith("aplay_status="):
        write_text(os.path.join(path, "result.txt"), status + "\n")
    else:
        write_text(os.path.join(path, "sweep-status.txt"), status + "\n")
    write_json(os.path.join(path, "mic-capture-analysis.json"), metrics)
    return path


def analyze_runs(root: str) -> list[dict[str, Any]]:
    runs = summarizer.find_runs([root])
    for run in runs:
        run["analysis"] = summarizer.quality_analysis(
            run,
            BAD_BASELINE,
            max_env_cv=0.20,
            max_env_low_pct=10.0,
            max_env_range_db=6.0,
            max_freq_error_pct=1.0,
            max_harmonic_ratio=0.05,
            max_clip_pct=1.0,
            min_mic_rms=0.003,
        )
    return sorted(runs, key=summarizer.rank_key)


def assert_summary_verdicts() -> None:
    assert summarizer.parse_dir_hint("01-threshold-frame") == {
        "dma_op_mode": "threshold",
    }
    assert summarizer.parse_dir_hint("02-threshold-32") == {
        "dma_op_mode": "threshold",
        "max_tx_thres": "32",
    }

    with tempfile.TemporaryDirectory(prefix="nq-audio-analysis-test-") as tmp:
        bad = dict(GOOD_METRICS)
        bad.update(
            {
                "zero_cross_freq_hz": 457.2,
                "zero_cross_freq_error_pct": 3.91,
                "envelope_cv_25ms": 0.63,
                "envelope_low_pct_25ms": 28.6,
                "envelope_peak_to_trough_db_25ms": 23.3,
                "harmonic_power_ratio_2_8": 0.1,
            }
        )

        add_run(tmp, "00-element", "aplay_status=0", bad)
        threshold = add_run(tmp, "01-threshold-32", "aplay_status=0", dict(GOOD_METRICS))
        xrun = add_run(tmp, "02-xrun", "aplay_status=0", dict(GOOD_METRICS))
        sync = add_run(tmp, "03-sync", "aplay_status=0", dict(GOOD_METRICS))
        add_run(tmp, "04-failed", "7", dict(GOOD_METRICS))
        mismatch = add_run(tmp, "05-mismatch", "aplay_status=0", dict(GOOD_METRICS))
        quiet_metrics = dict(GOOD_METRICS)
        quiet_metrics.update({"rms": 0.0005, "expected_tone_rms": 0.0})
        add_run(tmp, "06-quiet", "aplay_status=0", quiet_metrics)
        bad_frame = add_run(tmp, "07-threshold-frame-missing", "aplay_status=0", dict(GOOD_METRICS))
        missing_reinit = add_run(tmp, "08-missing-reinit", "aplay_status=0", dict(GOOD_METRICS))
        partial_hw = add_run(tmp, "09-partial-hw", "aplay_status=0", dict(GOOD_METRICS))

        write_text(
            os.path.join(threshold, "mcbsp-sysfs-config.txt"),
            "\n".join(
                [
                    "--- write /sys/devices/platform/40122000.mcbsp/dma_op_mode = threshold",
                    "--- read /sys/devices/platform/40122000.mcbsp/dma_op_mode",
                    "element [threshold]",
                    "--- write /sys/devices/platform/40122000.mcbsp/max_tx_thres = 32",
                    "--- read /sys/devices/platform/40122000.mcbsp/max_tx_thres",
                    "32",
                    "",
                ]
            ),
        )
        write_text(
            os.path.join(threshold, "case-plan.txt"),
            "case=threshold-32\nburst_bits=16\nmcbsp_tx_burst=16\n"
            "mcbsp_trigger_threshold=1\nbclk_fs=32\ncodec_power_first=1\n",
        )
        write_text(
            os.path.join(threshold, "aplay.log"),
            "starting aplay: /tmp/nq-both-440-48000-s16.wav\n"
            "pcm_status_wait_state=RUNNING attempts=5\n"
            "\n"
            "=== ALSA status during playback ===\n"
            "--- /proc/asound/card0/pcm0p/sub0/hw_params sample=initial\n"
            "access: RW_INTERLEAVED\n"
            "format: S16_LE\n"
            "subformat: STD\n"
            "channels: 2\n"
            "rate: 48000 (48000/1)\n"
            "period_size: 1024\n"
            "buffer_size: 4096\n"
            "--- /proc/asound/card0/pcm0p/sub0/status sample=initial\n"
            "state: RUNNING\n"
            "owner_pid   : 123\n"
            "trigger_time: 12.000000000\n"
            "tstamp      : 12.100000000\n"
            "delay       : 2048\n"
            "avail       : 2048\n"
            "avail_max   : 2048\n"
            "-----\n"
            "hw_ptr      : 8192\n"
            "appl_ptr    : 10240\n"
            "\n"
            "=== ALSA status samples during playback ===\n"
            "--- /proc/asound/card0/pcm0p/sub0/status sample=0\n"
            "state: RUNNING\n"
            "delay       : 2048\n"
            "avail       : 2048\n"
            "avail_max   : 2048\n"
            "-----\n"
            "hw_ptr      : 9216\n"
            "appl_ptr    : 11264\n"
            "--- /proc/asound/card0/pcm0p/sub0/status sample=1\n"
            "state: RUNNING\n"
            "delay       : 2048\n"
            "avail       : 2048\n"
            "avail_max   : 2048\n"
            "-----\n"
            "hw_ptr      : 10240\n"
            "appl_ptr    : 12288\n"
            "\n"
            "=== interrupt snapshot during playback ===\n"
            "--- /proc/interrupts sample=initial\n"
            " 35:        100     GIC-0  35 Level     4a056000.dma-controller\n"
            " 36:         50     GIC-0  36 Level     40122000.mcbsp\n"
            " 37:          7     GIC-0  37 Level     unrelated\n"
            "\n"
            "=== interrupt samples during playback ===\n"
            "--- /proc/interrupts sample=0\n"
            " 35:        110     GIC-0  35 Level     4a056000.dma-controller\n"
            " 36:         50     GIC-0  36 Level     40122000.mcbsp\n"
            "--- /proc/interrupts sample=1\n"
            " 35:        124     GIC-0  35 Level     4a056000.dma-controller\n"
            " 36:         52     GIC-0  36 Level     40122000.mcbsp\n"
            "\n"
            "=== dmesg tail during playback ===\n"
            "[   11.950000] steelhead-tas5713 sound-tas5713: nq steelhead trigger "
            "cmd=START codec_power_first=1 mute=0\n"
            "[   12.000000] tas571x 4-001b: nq tas571x legacy-stream-reinit keep_mclk=1 override=1\n"
            "[   12.650000] tas571x 4-001b: nq tas571x unmute sdi[0x04]=0x03\n"
            "[   12.700000] omap-dma 4a056000.dma-controller: nq dma-start ch=18 sig=17 dir=1 "
            "sgidx=0 ccr=0x010050a0 csdp=0x00002041 cicr=0x0103 csr=0x0000 "
            "cen=1024 cfn=4 cssa=0x9a000000 cdsa=0x40122008 csei=0x00000000 "
            "csfi=0x00000000 cdei=0x00000000 cdfi=0x00000020 clnk=0x8012 "
            "cdac=0x00000000 irq_count=0 irq_mask=0x00040000 "
            "irqenable_l1=0x00040000 irqstatus_l1=0x00000000\n"
            "[   12.705000] omap-mcbsp 40122000.mcbsp: nq mcbsp start stream=playback "
            "tx=1 rx=0 enable_srg=1 spcr2_before=0x0000 spcr1_before=0x0000 "
            "spcr2_after=0x00c1 spcr1_after=0x0000 xready=1 rready=0 "
            "xrst_reset=1 rrst_reset=0 xccr=0x0000 rccr=0x0001 irqen=0x0001 "
            "irqst=0x0000 xbuffstat=0x0010 rbuffstat=0x0000\n"
            "[   12.800000] omap-dma 4a056000.dma-controller: nq dma-irq order-marker\n"
            "aplay_exit=0\n",
        )
        write_text(
            os.path.join(threshold, "interrupts-before.txt"),
            " 35:         90     GIC-0  35 Level     4a056000.dma-controller\n"
            " 36:         48     GIC-0  36 Level     40122000.mcbsp\n",
        )
        write_text(
            os.path.join(threshold, "interrupts-after.txt"),
            " 35:        130     GIC-0  35 Level     4a056000.dma-controller\n"
            " 36:         52     GIC-0  36 Level     40122000.mcbsp\n",
        )
        write_text(
            os.path.join(threshold, "audio-kernel-events.txt"),
            "42: omap-dma 4a056000.dma-controller: nq cyclic dir=1 sig=17 "
            "ccr=0x01005020 csdp=0x00002041 cicr=0x0103 clnk=0x8012 "
            "en=1024 fn=4 fi=32 es=1 burst=32 dev=0x40122008 buf=0x8 "
            "period=4096 len=16384 flags=0x3\n"
            "43: omap-dma 4a056000.dma-controller: nq dma-start ch=18 sig=17 dir=1 "
            "sgidx=0 ccr=0x010050a0 csdp=0x00002041 cicr=0x0103 csr=0x0000 "
            "cen=1024 cfn=4 cssa=0x9a000000 cdsa=0x40122008 csei=0x00000000 "
            "csfi=0x00000000 cdei=0x00000000 cdfi=0x00000020 clnk=0x8012 "
            "cdac=0x00000000 irq_count=0 irq_mask=0x00040000 "
            "irqenable_l1=0x00040000 irqstatus_l1=0x00000000\n"
            "44: [   12.000000] omap-dma 4a056000.dma-controller: nq dma-irq ch=18 sig=17 "
            "dir=1 count=23 status=0x0008 ccr=0x010050a0 csr=0x0000 cen=1024 "
            "cfn=4 cssa=0x9a000000 cdsa=0x40122008 cdac=0x9a001000 "
            "clnk=0x8012 irq_mask=0x00040000 irqenable_l1=0x00040000 "
            "irqstatus_l1=0x00000000\n"
            "45: [   12.500000] omap-dma 4a056000.dma-controller: nq dma-irq ch=18 sig=17 "
            "dir=1 count=24 status=0x0008 ccr=0x010050a0 csr=0x0000 cen=1024 "
            "cfn=4 cssa=0x9a000000 cdsa=0x40122008 cdac=0x9a001800 "
            "clnk=0x8012 irq_mask=0x00040000 irqenable_l1=0x00040000 "
            "irqstatus_l1=0x00000000\n"
            "46: omap-dma 4a056000.dma-controller: nq dma-stopped ch=18 sig=17 dir=1 "
            "sgidx=0 ccr=0x01005020 csdp=0x00002041 cicr=0x0103 csr=0x0002 "
            "cen=1024 cfn=4 cssa=0x9a000000 cdsa=0x40122008 csei=0x00000000 "
            "csfi=0x00000000 cdei=0x00000000 cdfi=0x00000020 clnk=0x8012 "
            "cdac=0x9a002000 irq_count=24 irq_mask=0x00040000 "
            "irqenable_l1=0x00040000 irqstatus_l1=0x00000000\n"
            "43: omap-mcbsp 40122000.mcbsp: nq mcbsp start stream=playback "
            "tx=1 rx=0 enable_srg=1 spcr2_before=0x0000 spcr1_before=0x0000 "
            "spcr2_after=0x00c1 spcr1_after=0x0000 xready=1 rready=0 "
            "xrst_reset=1 rrst_reset=0 xccr=0x0000 rccr=0x0001 irqen=0x0001 "
            "irqst=0x0000 xbuffstat=0x0010 rbuffstat=0x0000\n"
            "43: omap-mcbsp 40122000.mcbsp: nq mcbsp stop stream=playback "
            "tx=1 rx=0 idle=1 spcr2_before=0x00c3 spcr1_before=0x0000 "
            "xccr_before=0x0000 rccr_before=0x0001 irqen_before=0x0001 "
            "irqst_before=0x0001 xbuffstat_before=0x0000 rbuffstat_before=0x0000 "
            "thrsh2_before=0x0000 thrsh1_before=0x0000 spcr2_after=0x0000 "
            "spcr1_after=0x0000 xccr_after=0x0001 rccr_after=0x0001 "
            "irqen_after=0x0000 irqst_after=0x0001 xbuffstat_after=0x0000 "
            "rbuffstat_after=0x0000 thrsh2_after=0x0000 thrsh1_after=0x0000\n"
            "44: omap-mcbsp 40122000.mcbsp: nq mcbsp hw stream=playback "
            "mode=threshold legacy_element=1 legacy_threshold_frame=1 "
            "trigger_threshold=1 "
            "period_words=512 max_thrsh=1264 pkt_size=0 threshold_words=512 "
            "maxburst=0 channels=2 width=16\n"
            "45: steelhead-tas5713 sound-tas5713: nq steelhead trigger "
            "cmd=START codec_power_first=1 mute=0\n"
            "45: tas571x 4-001b: nq tas571x legacy-stream-reinit keep_mclk=1 "
            "override=1\n"
            "46: tas571x 4-001b: nq tas571x probe legacy_power=1 "
            "stream_reinit_default=0 stream_reinit_override=1 "
            "mute_on_trigger=1 mute_on_trigger_param=-1\n"
            "47: tas571x 4-001b: nq tas571x unmute sdi[0x04]=0x03\n"
            "48: tas571x 4-001b: nq tas571x unmute sys2[0x05]=0x00\n"
            "49: tas571x 4-001b: nq tas571x unmute err[0x02]=0x00\n"
            "50: tas571x 4-001b: nq tas571x unmute mvol[0x07]=0x30\n"
            "51: steelhead-tas5713 sound-tas5713: nq steelhead hw_params "
            "format=i2s inversion=nb-nf legacy_s16_only=1 rate=48000 "
            "width=16 physical_width=16 channels=2 mclk=12288000 "
            "mcbsp=24576000 bclk_fs=32 bclk=1536000 "
            "bclk_override=32 div=16 cpu_fmt=0x4011 codec_fmt=0x4014\n"
            "52: omap-mcbsp 40122000.mcbsp: IRQEN: 0x0001\n"
            "53: omap-mcbsp 40122000.mcbsp: IRQST: 0x0000\n"
            "54: omap-mcbsp 40122000.mcbsp: XBUFFSTAT: 0x0010\n"
            "55: omap-mcbsp 40122000.mcbsp: RBUFFSTAT: 0x0000\n"
            "56: omap-mcbsp 40122000.mcbsp: THRSH2: 0x0000\n"
            "57: omap-mcbsp 40122000.mcbsp: THRSH1: 0x0000\n"
            "58: tas571x 4-001b: nq tas571x pre-mute sys2[0x05]=0x00\n"
            "59: tas571x 4-001b: nq tas571x pre-mute err[0x02]=0x00\n"
            "60: tas571x 4-001b: nq tas571x pre-mute mvol[0x07]=0x30\n",
        )
        write_text(
            os.path.join(xrun, "audio-register-events.txt"),
            "123: omap-mcbsp 40122000.mcbsp: TX Buffer Underflow!\n",
        )
        write_text(
            os.path.join(sync, "aplay.log"),
            "211: ALSA pcm0p: XSYNC error during playback\n",
        )
        write_text(
            os.path.join(mismatch, "mcbsp-sysfs-config.txt"),
            "\n".join(
                [
                    "--- write /sys/devices/platform/40122000.mcbsp/dma_op_mode = threshold",
                    "--- read /sys/devices/platform/40122000.mcbsp/dma_op_mode",
                    "[element] threshold",
                    "",
                ]
            ),
        )
        write_text(
            os.path.join(bad_frame, "mcbsp-sysfs-config.txt"),
            "\n".join(
                [
                    "--- write /sys/devices/platform/40122000.mcbsp/dma_op_mode = threshold",
                    "--- read /sys/devices/platform/40122000.mcbsp/dma_op_mode",
                    "element [threshold]",
                    "",
                ]
            ),
        )
        write_text(
            os.path.join(bad_frame, "audio-kernel-events.txt"),
            "42: omap-mcbsp 40122000.mcbsp: nq mcbsp hw stream=playback "
            "mode=threshold legacy_element=1 legacy_threshold_frame=0 "
            "period_words=512 max_thrsh=1264 pkt_size=32 threshold_words=32 "
            "maxburst=32 channels=2 width=16\n"
            "43: tas571x 4-001b: nq tas571x legacy-stream-reinit keep_mclk=1 "
            "override=1\n",
        )
        write_text(
            os.path.join(partial_hw, "aplay.log"),
            "starting aplay: /tmp/nq-both-440-48000-s16.wav\n"
            "=== ALSA status during playback ===\n"
            "--- /proc/asound/card0/pcm0p/sub0/hw_params sample=initial\n"
            "format: S16_LE\n",
        )

        runs = analyze_runs(tmp)
        by_run = {run["run"]: run for run in runs}
        table_buf = io.StringIO()
        with redirect_stdout(table_buf):
            summarizer.print_table(runs)
        table = table_buf.getvalue()

        assert runs[0]["run"] == "01-threshold-32", runs
        assert by_run["01-threshold-32"]["analysis"]["verdict"] == "candidate"
        assert by_run["01-threshold-32"]["analysis"]["env_improvement_x"] > 7.0
        assert by_run["01-threshold-32"]["dma_op_mode"] == "threshold"
        assert by_run["01-threshold-32"]["max_tx_thres"] == "32"
        assert by_run["01-threshold-32"]["case_plan"]["burst_bits"] == "16"
        assert by_run["01-threshold-32"]["case_plan"]["mcbsp_tx_burst"] == "16"
        assert by_run["01-threshold-32"]["case_plan"]["mcbsp_trigger_threshold"] == "1"
        assert by_run["01-threshold-32"]["case_plan"]["bclk_fs"] == "32"
        assert by_run["01-threshold-32"]["case_plan"]["codec_power_first"] == "1"
        assert by_run["01-threshold-32"]["pcm_hw_params"]["format"] == "S16_LE"
        assert by_run["01-threshold-32"]["pcm_hw_params"]["rate"] == "48000 (48000/1)"
        assert by_run["01-threshold-32"]["pcm_hw_params"]["channels"] == "2"
        assert by_run["01-threshold-32"]["pcm_hw_params"]["period_size"] == "1024"
        assert by_run["01-threshold-32"]["pcm_hw_params"]["buffer_size"] == "4096"
        assert by_run["01-threshold-32"]["pcm_status"]["pcm_status_wait_state"] == "RUNNING"
        assert by_run["01-threshold-32"]["pcm_status"]["attempts"] == "5"
        assert by_run["01-threshold-32"]["pcm_status"]["state"] == "RUNNING"
        assert by_run["01-threshold-32"]["pcm_status"]["delay"] == "2048"
        assert by_run["01-threshold-32"]["pcm_status"]["avail"] == "2048"
        assert by_run["01-threshold-32"]["pcm_status"]["hw_ptr"] == "10240"
        assert by_run["01-threshold-32"]["pcm_status"]["appl_ptr"] == "12288"
        assert by_run["01-threshold-32"]["pcm_status"]["sample_count"] == 3
        assert by_run["01-threshold-32"]["pcm_status"]["first_hw_ptr"] == "8192"
        assert by_run["01-threshold-32"]["pcm_status"]["last_hw_ptr"] == "10240"
        assert by_run["01-threshold-32"]["pcm_status"]["hw_ptr_delta"] == "2048"
        assert by_run["01-threshold-32"]["pcm_status"]["first_appl_ptr"] == "10240"
        assert by_run["01-threshold-32"]["pcm_status"]["last_appl_ptr"] == "12288"
        assert by_run["01-threshold-32"]["pcm_status"]["appl_ptr_delta"] == "2048"
        pcm_progress = triage_tool.pcm_progress_health([by_run["01-threshold-32"]])
        assert pcm_progress["status"] == "advancing", pcm_progress
        assert pcm_progress["max_hw_ptr_delta"] == 2048, pcm_progress
        assert by_run["01-threshold-32"]["proc_interrupts"]["sample_count"] == 3
        assert by_run["01-threshold-32"]["proc_interrupts"]["active_delta_total"] == 26
        assert by_run["01-threshold-32"]["proc_interrupts"]["before_after_delta_total"] == 44
        assert "4a056000.dma-controller:24" in by_run["01-threshold-32"]["proc_interrupts"]["active_top"]
        assert by_run["01-threshold-32"]["event_order"]["sequence"].startswith(
            "steelhead-trigger>tas-reinit>tas-unmute>dma-start>mcbsp-start>dma-irq>aplay-exit"
        )
        assert round(by_run["01-threshold-32"]["event_order"]["tas_unmute_to_dma_ms"], 3) == 50.0
        assert round(by_run["01-threshold-32"]["event_order"]["dma_to_mcbsp_ms"], 3) == 5.0
        assert round(by_run["01-threshold-32"]["event_order"]["mcbsp_to_dmairq_ms"], 3) == 95.0
        assert by_run["01-threshold-32"]["mcbsp_sysfs"]["actual"]["dma_op_mode"] == "threshold"
        assert by_run["01-threshold-32"]["mcbsp_stop"]["latest"]["irqst_before"] == "0x0001"
        assert by_run["01-threshold-32"]["mcbsp_stop"]["latest"]["xbuffstat_before"] == "0x0000"
        assert by_run["01-threshold-32"]["tas571x"]["phases"]["pre-mute"]["err"] == "0x00"
        assert by_run["01-threshold-32"]["tas571x"]["phases"]["pre-mute"]["mvol"] == "0x30"
        assert by_run["01-threshold-32"]["dma_cyclic"]["sig"] == "17"
        assert by_run["01-threshold-32"]["dma_cyclic"]["csdp"] == "0x00002041"
        assert by_run["01-threshold-32"]["dma_cyclic"]["clnk"] == "0x8012"
        assert by_run["01-threshold-32"]["dma_start"]["phase"] == "start"
        assert by_run["01-threshold-32"]["dma_start"]["ccr"] == "0x010050a0"
        assert by_run["01-threshold-32"]["dma_start"]["clnk"] == "0x8012"
        assert by_run["01-threshold-32"]["dma_start"]["irq_count"] == "0"
        assert by_run["01-threshold-32"]["dma_start"]["irqenable_l1"] == "0x00040000"
        assert by_run["01-threshold-32"]["dma_irq"]["latest"]["count"] == "24"
        assert by_run["01-threshold-32"]["dma_irq"]["latest"]["status"] == "0x0008"
        assert by_run["01-threshold-32"]["dma_irq"]["latest"]["cdac"] == "0x9a001800"
        assert by_run["01-threshold-32"]["dma_irq"]["latest"]["irq_mask"] == "0x00040000"
        assert by_run["01-threshold-32"]["dma_irq"]["intervals_ms"] == [500.0]
        assert by_run["01-threshold-32"]["dma_irq"]["interval_avg_ms"] == 500.0
        assert by_run["01-threshold-32"]["dma_stop"]["phase"] == "stopped"
        assert by_run["01-threshold-32"]["dma_stop"]["csr"] == "0x0002"
        assert by_run["01-threshold-32"]["dma_stop"]["cdac"] == "0x9a002000"
        assert by_run["01-threshold-32"]["dma_stop"]["irq_count"] == "24"
        assert by_run["01-threshold-32"]["dma_stop"]["irqstatus_l1"] == "0x00000000"
        assert by_run["01-threshold-32"]["mcbsp_hw"]["latest"]["mode"] == "threshold"
        assert by_run["01-threshold-32"]["mcbsp_hw"]["latest"]["legacy_threshold_frame"] == "1"
        assert by_run["01-threshold-32"]["mcbsp_hw"]["latest"]["trigger_threshold"] == "1"
        assert by_run["01-threshold-32"]["mcbsp_hw"]["latest"]["period_words"] == "512"
        assert by_run["01-threshold-32"]["mcbsp_hw"]["latest"]["pkt_size"] == "0"
        assert by_run["01-threshold-32"]["mcbsp_hw"]["latest"]["threshold_words"] == "512"
        assert by_run["01-threshold-32"]["mcbsp_start"]["latest"]["stream"] == "playback"
        assert by_run["01-threshold-32"]["mcbsp_start"]["latest"]["xready"] == "1"
        assert by_run["01-threshold-32"]["mcbsp_start"]["latest"]["xrst_reset"] == "1"
        assert by_run["01-threshold-32"]["analysis"]["mcbsp_start"]["xrst_reset"] == "1"
        assert by_run["01-threshold-32"]["mcbsp_regs"]["irqen"] == "0x0001"
        assert by_run["01-threshold-32"]["mcbsp_regs"]["irqst"] == "0x0000"
        assert by_run["01-threshold-32"]["mcbsp_regs"]["xbuffstat"] == "0x0010"
        assert by_run["01-threshold-32"]["mcbsp_regs"]["rbuffstat"] == "0x0000"
        assert by_run["01-threshold-32"]["mcbsp_regs"]["thrsh2"] == "0x0000"
        assert by_run["01-threshold-32"]["mcbsp_regs"]["thrsh1"] == "0x0000"
        assert by_run["01-threshold-32"]["steelhead_audio"]["phases"]["hw_params"]["format"] == "i2s"
        assert by_run["01-threshold-32"]["steelhead_audio"]["phases"]["hw_params"]["inversion"] == "nb-nf"
        assert by_run["01-threshold-32"]["steelhead_audio"]["phases"]["hw_params"]["legacy_s16_only"] == "1"
        assert by_run["01-threshold-32"]["steelhead_audio"]["phases"]["hw_params"]["bclk_override"] == "32"
        assert by_run["01-threshold-32"]["steelhead_audio"]["phases"]["hw_params"]["bclk"] == "1536000"
        assert by_run["01-threshold-32"]["steelhead_audio"]["phases"]["hw_params"]["div"] == "16"
        assert by_run["01-threshold-32"]["steelhead_audio"]["phases"]["trigger"]["cmd"] == "START"
        assert by_run["01-threshold-32"]["steelhead_audio"]["phases"]["trigger"]["codec_power_first"] == "1"
        assert by_run["01-threshold-32"]["steelhead_audio"]["phases"]["trigger"]["mute"] == "0"
        assert by_run["01-threshold-32"]["tas571x"]["latest"]["sdi"] == "0x03"
        assert by_run["01-threshold-32"]["tas571x"]["latest"]["sys2"] == "0x00"
        assert by_run["01-threshold-32"]["tas571x"]["latest"]["err"] == "0x00"
        assert by_run["01-threshold-32"]["tas571x"]["latest"]["mvol"] == "0x30"
        assert by_run["01-threshold-32"]["tas571x"]["legacy_reinit"]["latest"]["keep_mclk"] == "1"
        assert by_run["01-threshold-32"]["tas571x"]["legacy_reinit"]["latest"]["override"] == "1"
        assert by_run["01-threshold-32"]["tas571x"]["probe"]["latest"]["mute_on_trigger"] == "1"
        assert by_run["01-threshold-32"]["tas571x"]["probe"]["latest"]["mute_on_trigger_param"] == "-1"
        assert "cpwr" in table
        assert "steelhead-trigger>tas-reinit" in table

        assert "flutter" in by_run["00-element"]["analysis"]["verdict"]
        assert "dropout" in by_run["00-element"]["analysis"]["verdict"]
        assert "pumping" in by_run["00-element"]["analysis"]["verdict"]
        assert "freq" in by_run["00-element"]["analysis"]["verdict"]

        assert by_run["02-xrun"]["kernel_events"]["flags"] == ["xrun"]
        assert "xrun" in by_run["02-xrun"]["analysis"]["verdict"]
        assert "sync" in by_run["03-sync"]["analysis"]["verdict"]
        assert "alsa-error" in by_run["03-sync"]["analysis"]["verdict"]
        assert "failed" in by_run["04-failed"]["analysis"]["verdict"]
        assert "dma_op_mode-mismatch" in by_run["05-mismatch"]["analysis"]["verdict"]
        assert "quiet" in by_run["06-quiet"]["analysis"]["verdict"]
        assert "threshold-frame-missing" in by_run["07-threshold-frame-missing"]["analysis"]["verdict"]
        assert "threshold-frame-packet" in by_run["07-threshold-frame-missing"]["analysis"]["verdict"]
        assert "threshold-frame-threshold" in by_run["07-threshold-frame-missing"]["analysis"]["verdict"]
        assert "tas-reinit-missing" in by_run["08-missing-reinit"]["analysis"]["verdict"]


def assert_sweep_triage() -> None:
    with tempfile.TemporaryDirectory(prefix="nq-audio-triage-test-") as tmp:
        good = add_run(tmp, "01-threshold-32", "aplay_status=0", dict(GOOD_METRICS))
        bad_metrics = dict(GOOD_METRICS)
        bad_metrics.update({"envelope_cv_25ms": 0.7, "envelope_low_pct_25ms": 30.0})
        add_run(tmp, "00-element", "aplay_status=0", bad_metrics)
        write_text(
            os.path.join(good, "mcbsp-sysfs-config.txt"),
            "\n".join(
                [
                    "--- write /sys/devices/platform/40122000.mcbsp/dma_op_mode = threshold",
                    "--- read /sys/devices/platform/40122000.mcbsp/dma_op_mode",
                    "element [threshold]",
                    "",
                ]
            ),
        )
        write_text(
            os.path.join(good, "audio-kernel-events.txt"),
            "1: tas571x 4-001b: nq tas571x legacy-stream-reinit keep_mclk=1 override=1\n",
        )
        write_text(os.path.join(good, "case-plan.txt"), "case=legacy-parity\n")
        runs = analyze_runs(tmp)
        result = triage_tool.triage(runs)
        assert result["status"] == "candidate", result
        assert result["candidate_run"] == "01-threshold-32", result
        assert result["candidate_settings"]["dma_op_mode"] == "threshold", result
        assert result["candidate_settings"]["max_tx_thres"] == "32", result
        assert "NQ_MCBSP_DMA_OP_MODE=threshold" in result["candidate_retest_command"], result
        assert "NQ_MCBSP_MAX_TX_THRES=32" in result["candidate_retest_command"], result
        assert "RUN_CASES=legacy-parity" in result["candidate_module_retest_command"], result
        assert "BUILD_MODULES=0" in result["candidate_module_retest_command"], result
        assert "FASTBOOT_BOOT=0" in result["candidate_module_retest_command"], result
        assert (
            "tools/run_audio_module_reload_sweep_local.sh"
            in result["candidate_module_retest_command"]
        ), result

    with tempfile.TemporaryDirectory(prefix="nq-audio-triage-test-") as tmp:
        bad_metrics = dict(GOOD_METRICS)
        bad_metrics.update({"envelope_cv_25ms": 0.7, "envelope_low_pct_25ms": 30.0})
        bad = add_run(tmp, "00-element", "aplay_status=0", bad_metrics)
        write_text(
            os.path.join(bad, "audio-kernel-events.txt"),
            "1: tas571x 4-001b: nq tas571x legacy-stream-reinit keep_mclk=1 override=1\n",
        )
        write_text(os.path.join(bad, "case-plan.txt"), "case=mainline-packet\n")
        runs = analyze_runs(tmp)
        result = triage_tool.triage(runs)
        assert result["status"] == "needs-investigation", result
        assert "distorted" in result["next_step"], result
        assert result["best_settings"]["dma_op_mode"] == "element", result
        assert "NQ_MCBSP_DMA_OP_MODE=element" in result["best_retest_command"], result
        assert "RUN_CASES=mainline-packet" in result["best_module_retest_command"], result

    dma_bad_metrics = dict(GOOD_METRICS)
    dma_bad_metrics.update({"envelope_cv_25ms": 0.7, "envelope_low_pct_25ms": 30.0})
    missing_dma_run = {
        "run": "00-missing-dma",
        "metrics": dma_bad_metrics,
        "analysis": {"verdict": "flutter,dropout,pumping"},
        "dma_start": {"phase": "start"},
        "dma_stop": {
            "phase": "stopped",
            "irq_count": "0",
            "irq_mask": "0x00040000",
            "irqenable_l1": "0x00040000",
            "irqstatus_l1": "0x00000000",
        },
    }
    result = triage_tool.triage([missing_dma_run])
    assert result["status"] == "needs-investigation", result
    assert result["dma_health"]["status"] == "missing-callbacks", result
    assert "no cyclic period callbacks" in result["next_step"], result

    masked_dma_run = dict(missing_dma_run)
    masked_dma_run["run"] = "01-masked-dma"
    masked_dma_run["dma_stop"] = dict(missing_dma_run["dma_stop"])
    masked_dma_run["dma_stop"]["irq_mask"] = "0x00000000"
    result = triage_tool.triage([masked_dma_run])
    assert result["dma_health"]["status"] == "irq-masked", result
    assert "appear masked" in result["next_step"], result

    serviced_dma_run = dict(missing_dma_run)
    serviced_dma_run["run"] = "02-serviced-dma"
    serviced_dma_run["dma_stop"] = dict(missing_dma_run["dma_stop"])
    serviced_dma_run["dma_stop"]["irq_count"] = "24"
    result = triage_tool.triage([serviced_dma_run])
    assert result["dma_health"]["status"] == "callbacks-present", result
    assert "McBSP framing" in result["next_step"], result

    stalled_pcm_run = dict(missing_dma_run)
    stalled_pcm_run["run"] = "03-stalled-pcm"
    stalled_pcm_run["dma_start"] = {}
    stalled_pcm_run["dma_stop"] = {}
    stalled_pcm_run["pcm_status"] = {
        "state": "RUNNING",
        "sample_count": 3,
        "hw_ptr_delta": "0",
        "appl_ptr_delta": "2048",
    }
    result = triage_tool.triage([stalled_pcm_run])
    assert result["pcm_progress"]["status"] == "stalled-hwptr", result
    assert "hw_ptr did not advance" in result["next_step"], result

    advancing_bad_run = dict(serviced_dma_run)
    advancing_bad_run["run"] = "04-advancing-bad"
    advancing_bad_run["pcm_status"] = {
        "state": "RUNNING",
        "sample_count": 3,
        "hw_ptr_delta": "4096",
        "appl_ptr_delta": "4096",
    }
    result = triage_tool.triage([advancing_bad_run])
    assert result["pcm_progress"]["status"] == "advancing", result
    assert "DMA cyclic callbacks and ALSA hw_ptr progress" in result["next_step"], result

    mcbsp_irq_run = dict(serviced_dma_run)
    mcbsp_irq_run["run"] = "05-mcbsp-stop-irq"
    mcbsp_irq_run["mcbsp_stop"] = {
        "latest": {
            "irqst_before": "0x0001",
            "xbuffstat_before": "0x0000",
        },
        "events": [],
    }
    result = triage_tool.triage([mcbsp_irq_run])
    assert result["mcbsp_stop"]["status"] == "stop-irq-pending", result
    assert "McBSP stop-state shows pending IRQ status" in result["next_step"], result

    tas_error_run = dict(serviced_dma_run)
    tas_error_run["run"] = "06-tas-error"
    tas_error_run["tas571x"] = {
        "phases": {
            "pre-mute": {
                "err": "0x04",
                "sys2": "0x00",
            }
        }
    }
    result = triage_tool.triage([tas_error_run])
    assert result["tas571x"]["status"] == "codec-error-latched", result
    assert "TAS5713 ERR latched" in result["next_step"], result


def assert_multi_root_run_names() -> None:
    with tempfile.TemporaryDirectory(prefix="nq-audio-multiroot-test-") as tmp:
        sweep_a = os.path.join(tmp, "sweep-a")
        sweep_b = os.path.join(tmp, "sweep-b")
        os.makedirs(sweep_a)
        os.makedirs(sweep_b)
        add_run(sweep_a, "00-element", "aplay_status=0", dict(GOOD_METRICS))
        add_run(sweep_b, "00-element", "aplay_status=0", dict(GOOD_METRICS))

        runs = summarizer.find_runs([sweep_a, sweep_b])
        names = sorted(run["run"] for run in runs)
        assert names == ["sweep-a/00-element", "sweep-b/00-element"], names


def main() -> int:
    assert_signal_metrics()
    assert_summary_verdicts()
    assert_sweep_triage()
    assert_multi_root_run_names()
    print("audio-analysis-tests-ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
