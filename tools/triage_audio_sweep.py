#!/usr/bin/env python3
"""Suggest the next action from a Nexus Q audio sweep summary."""

from __future__ import annotations

import argparse
import json
import math
import os
import shlex
from typing import Any


MODULE_RELOAD_CASES = frozenset(
    {
        "legacy-parity",
        "codec-first",
        "codec-first-link-only",
        "no-trigger-mute",
        "stop-on-underflow",
        "legacy-burst16",
        "mcbsp-txburst16",
        "trigger-threshold",
        "txburst-trigger-threshold",
        "forced-bclk32",
        "forced-bclk64",
        "no-dma-blockirq",
        "no-tas-reinit",
        "legacy-dma-packet",
        "mainline-packet",
        "mainline-packet-burst16",
        "mainline-dma",
        "i2s-nbnf",
        "i2s-nbif",
        "i2s-ibnf",
        "i2s-ibif",
        "leftj-nbnf",
        "leftj-nbif",
        "leftj-ibnf",
        "leftj-ibif",
    }
)


def load_runs(path: str) -> list[dict[str, Any]]:
    if os.path.isdir(path):
        path = os.path.join(path, "sweep-summary.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path} does not contain a sweep-summary run list")
    return [run for run in data if isinstance(run, dict)]


def metric(run: dict[str, Any], name: str) -> float:
    metrics = run.get("metrics")
    if not isinstance(metrics, dict):
        return math.nan
    value = metrics.get(name)
    return float(value) if isinstance(value, (int, float)) else math.nan


def analysis(run: dict[str, Any]) -> dict[str, Any]:
    value = run.get("analysis")
    return value if isinstance(value, dict) else {}


def verdict(run: dict[str, Any]) -> str:
    value = analysis(run).get("verdict")
    return str(value) if value else ""


def env_improvement(run: dict[str, Any]) -> float:
    value = analysis(run).get("env_improvement_x")
    return float(value) if isinstance(value, (int, float)) else math.nan


def sort_key(run: dict[str, Any]) -> tuple[int, float, float, float]:
    is_candidate = 0 if verdict(run) == "candidate" else 1
    env = metric(run, "envelope_cv_25ms")
    freq = abs(metric(run, "zero_cross_freq_error_pct"))
    harmonic = metric(run, "harmonic_power_ratio_2_8")
    return (
        is_candidate,
        env if not math.isnan(env) else math.inf,
        freq if not math.isnan(freq) else math.inf,
        harmonic if not math.isnan(harmonic) else math.inf,
    )


def latest_fields(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    latest = value.get("latest")
    return latest if isinstance(latest, dict) else {}


def run_basename(run: dict[str, Any]) -> str:
    return os.path.basename(str(run.get("run", "")))


def optional_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text if text and text.lower() != "none" else ""


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value), 0)
    except ValueError:
        return None


def dma_stop_fields(run: dict[str, Any]) -> dict[str, Any]:
    value = run.get("dma_stop")
    return value if isinstance(value, dict) else {}


def dma_irq_latest_fields(run: dict[str, Any]) -> dict[str, Any]:
    return latest_fields(run.get("dma_irq"))


def case_plan(run: dict[str, Any]) -> dict[str, Any]:
    value = run.get("case_plan")
    return value if isinstance(value, dict) else {}


def pcm_status_fields(run: dict[str, Any]) -> dict[str, Any]:
    value = run.get("pcm_status")
    return value if isinstance(value, dict) else {}


def pcm_hw_fields(run: dict[str, Any]) -> dict[str, Any]:
    value = run.get("pcm_hw_params")
    return value if isinstance(value, dict) else {}


def mcbsp_stop_latest_fields(run: dict[str, Any]) -> dict[str, Any]:
    return latest_fields(run.get("mcbsp_stop"))


def tas571x_phases(run: dict[str, Any]) -> dict[str, Any]:
    value = run.get("tas571x")
    if not isinstance(value, dict):
        return {}
    phases = value.get("phases")
    return phases if isinstance(phases, dict) else {}


def tas571x_pre_mute_fields(run: dict[str, Any]) -> dict[str, Any]:
    phase = tas571x_phases(run).get("pre-mute")
    return phase if isinstance(phase, dict) else {}


def dma_callback_count(run: dict[str, Any]) -> int | None:
    stop_count = parse_int(dma_stop_fields(run).get("irq_count"))
    if stop_count is not None:
        return stop_count
    return parse_int(dma_irq_latest_fields(run).get("count"))


def has_dma_evidence(run: dict[str, Any]) -> bool:
    return bool(run.get("dma_start") or run.get("dma_stop") or dma_irq_latest_fields(run))


def dma_health(runs: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [run for run in runs if has_dma_evidence(run)]
    if not observed:
        return {
            "status": "missing-evidence",
            "summary": "No DMA start/stop/IRQ diagnostic records were found.",
        }

    counts = [dma_callback_count(run) for run in observed]
    known_counts = [count for count in counts if count is not None]
    if not known_counts:
        return {
            "status": "unverified",
            "summary": "DMA records are present, but callback counts are not available in these logs.",
        }

    zero_count_runs = [
        run for run, count in zip(observed, counts) if count == 0
    ]
    positive_count_runs = [
        run for run, count in zip(observed, counts) if count is not None and count > 0
    ]

    masked_runs: list[str] = []
    pending_status_runs: list[str] = []
    for run in zero_count_runs:
        stop = dma_stop_fields(run)
        irq_mask = parse_int(stop.get("irq_mask"))
        irqenable_l1 = parse_int(stop.get("irqenable_l1"))
        irqstatus_l1 = parse_int(stop.get("irqstatus_l1"))
        if irq_mask == 0 or irqenable_l1 == 0:
            masked_runs.append(str(run.get("run", "")))
        if irqstatus_l1:
            pending_status_runs.append(str(run.get("run", "")))

    if masked_runs:
        return {
            "status": "irq-masked",
            "summary": (
                "DMA period callbacks were not observed and the DMA IRQ mask/enable "
                "state is zero for at least one run."
            ),
            "runs": masked_runs,
        }
    if len(zero_count_runs) == len(known_counts):
        result: dict[str, Any] = {
            "status": "missing-callbacks",
            "summary": (
                "DMA start/stop diagnostics ran, but no cyclic period callbacks "
                "were counted."
            ),
            "runs": [str(run.get("run", "")) for run in zero_count_runs],
        }
        if pending_status_runs:
            result["pending_irq_status_runs"] = pending_status_runs
        return result
    if positive_count_runs:
        return {
            "status": "callbacks-present",
            "summary": (
                "At least one run counted DMA cyclic callbacks; if audio is still "
                "bad, prioritize McBSP framing, FIFO timing, or TAS5713 state."
            ),
            "runs": [str(run.get("run", "")) for run in positive_count_runs],
            "max_count": max(known_counts),
        }
    return {
        "status": "unknown",
        "summary": "DMA diagnostics were inconclusive.",
    }


def mcbsp_stop_health(runs: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [run for run in runs if mcbsp_stop_latest_fields(run)]
    if not observed:
        return {
            "status": "missing-evidence",
            "summary": "No McBSP stop-state diagnostic records were found.",
        }

    irq_runs: list[str] = []
    for run in observed:
        irqst_before = parse_int(mcbsp_stop_latest_fields(run).get("irqst_before"))
        if irqst_before:
            irq_runs.append(str(run.get("run", "")))

    if irq_runs:
        return {
            "status": "stop-irq-pending",
            "summary": "McBSP IRQ status was non-zero immediately before stop.",
            "runs": irq_runs,
        }
    return {
        "status": "clean-stop-snapshot",
        "summary": "McBSP stop snapshots did not show pending IRQ status.",
        "runs": [str(run.get("run", "")) for run in observed],
    }


def tas571x_health(runs: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [run for run in runs if tas571x_pre_mute_fields(run)]
    if not observed:
        return {
            "status": "missing-pre-mute",
            "summary": "No TAS5713 pre-mute diagnostic register snapshot was found.",
        }

    err_runs: list[str] = []
    clean_runs: list[str] = []
    for run in observed:
        fields = tas571x_pre_mute_fields(run)
        err = parse_int(fields.get("err"))
        if err is None:
            continue
        if err:
            err_runs.append(str(run.get("run", "")))
        else:
            clean_runs.append(str(run.get("run", "")))

    if err_runs:
        return {
            "status": "codec-error-latched",
            "summary": "TAS5713 ERR was non-zero immediately before stream mute.",
            "runs": err_runs,
        }
    if clean_runs:
        return {
            "status": "pre-mute-clean",
            "summary": "TAS5713 pre-mute ERR snapshots were zero.",
            "runs": clean_runs,
        }
    return {
        "status": "unverified",
        "summary": "TAS5713 pre-mute snapshots were present but did not include ERR.",
    }


def pcm_progress_health(runs: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [run for run in runs if pcm_status_fields(run)]
    if not observed:
        return {
            "status": "missing-evidence",
            "summary": "No active ALSA PCM status samples were found.",
        }

    no_active_runs: list[str] = []
    insufficient_runs: list[str] = []
    stalled_runs: list[str] = []
    underrun_risk_runs: list[str] = []
    advancing_runs: list[str] = []
    max_hw_delta = 0

    for run in observed:
        status = pcm_status_fields(run)
        hw = pcm_hw_fields(run)
        run_name = str(run.get("run", ""))
        state = optional_str(status.get("state") or status.get("pcm_status_wait_state")).upper()
        sample_count = parse_int(status.get("sample_count"))
        hw_delta = parse_int(status.get("hw_ptr_delta"))
        buffer_size = parse_int(hw.get("buffer_size"))
        avail_max = parse_int(status.get("avail_max"))

        if state and state != "RUNNING":
            no_active_runs.append(run_name)
            continue
        if sample_count is None or sample_count < 2 or hw_delta is None:
            insufficient_runs.append(run_name)
            continue
        if hw_delta <= 0:
            stalled_runs.append(run_name)
            continue

        advancing_runs.append(run_name)
        max_hw_delta = max(max_hw_delta, hw_delta)
        if buffer_size is not None and avail_max is not None and avail_max >= buffer_size:
            underrun_risk_runs.append(run_name)

    if stalled_runs:
        return {
            "status": "stalled-hwptr",
            "summary": (
                "ALSA reported RUNNING samples, but hw_ptr did not advance for "
                "at least one run."
            ),
            "runs": stalled_runs,
        }
    if advancing_runs:
        result: dict[str, Any] = {
            "status": "advancing",
            "summary": "Repeated active PCM samples show hw_ptr progress.",
            "runs": advancing_runs,
            "max_hw_ptr_delta": max_hw_delta,
        }
        if underrun_risk_runs:
            result["underrun_risk_runs"] = underrun_risk_runs
            result["summary"] += " At least one run reached avail_max >= buffer_size."
        return result
    if len(no_active_runs) == len(observed):
        return {
            "status": "no-active-samples",
            "summary": "PCM status samples were captured, but none reached RUNNING.",
            "runs": no_active_runs,
        }
    if len(insufficient_runs) == len(observed):
        return {
            "status": "insufficient-samples",
            "summary": "PCM status evidence exists, but repeated hw_ptr samples are missing.",
            "runs": insufficient_runs,
        }
    return {
        "status": "unknown",
        "summary": "PCM progress diagnostics were inconclusive.",
    }


def recommended_settings(run: dict[str, Any]) -> dict[str, str]:
    mcbsp_hw = latest_fields(run.get("mcbsp_hw"))
    steelhead = run.get("steelhead_audio", {})
    steelhead_phases = steelhead.get("phases", {}) if isinstance(steelhead, dict) else {}
    steelhead_hw = (
        steelhead_phases.get("hw_params", {}) if isinstance(steelhead_phases, dict) else {}
    )

    settings: dict[str, str] = {}
    for key, value in (
        ("dma_op_mode", run.get("dma_op_mode")),
        ("max_tx_thres", run.get("max_tx_thres")),
        ("mcbsp_mode", mcbsp_hw.get("mode")),
        ("legacy_threshold_frame", mcbsp_hw.get("legacy_threshold_frame")),
        ("period_words", mcbsp_hw.get("period_words")),
        ("pkt_size", mcbsp_hw.get("pkt_size")),
        ("threshold_words", mcbsp_hw.get("threshold_words")),
        ("format", steelhead_hw.get("format")),
        ("inversion", steelhead_hw.get("inversion")),
        ("bclk", steelhead_hw.get("bclk")),
        ("div", steelhead_hw.get("div")),
    ):
        text = optional_str(value)
        if text:
            settings[key] = text

    if "threshold-frame" in run_basename(run):
        settings.setdefault("aplay_extra_args", "--period-size=512 --buffer-size=2048")
    return settings


def retest_command(run: dict[str, Any]) -> str:
    settings = recommended_settings(run)
    env = {
        "NQ_SPEAKER_CONNECTED": "1",
        "FFMPEG_INPUT": ":0",
        "FASTBOOT_BOOT": "1",
        "PROBE_CHANNELS": "both",
    }
    if settings.get("dma_op_mode"):
        env["NQ_MCBSP_DMA_OP_MODE"] = settings["dma_op_mode"]
    if settings.get("max_tx_thres"):
        env["NQ_MCBSP_MAX_TX_THRES"] = settings["max_tx_thres"]
    if settings.get("aplay_extra_args"):
        env["APLAY_EXTRA_ARGS"] = settings["aplay_extra_args"]

    parts = [f"{key}={shlex.quote(value)}" for key, value in env.items()]
    parts.append("tools/run_audio_legacydma_probe_local.sh")
    return " ".join(parts)


def module_retest_command(run: dict[str, Any]) -> str:
    case = optional_str(case_plan(run).get("case"))
    if not case or case not in MODULE_RELOAD_CASES:
        return ""

    env = {
        "NQ_SPEAKER_CONNECTED": "1",
        "FFMPEG_INPUT": ":0",
        "RUN_CASES": case,
        "RUN_PREFLIGHT": "0",
        "BUILD_MODULES": "0",
        "INSTALL_MODULES": "0",
        "FASTBOOT_BOOT": "0",
        "PROBE_CHANNELS": "both",
        "NQ_PROBE_MASTER_VOLUME": "120",
        "NQ_PROBE_SPEAKER_VOLUME": "130",
    }
    parts = [f"{key}={shlex.quote(value)}" for key, value in env.items()]
    parts.append("tools/run_audio_module_reload_sweep_local.sh")
    return " ".join(parts)


def reason_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in runs:
        for reason in verdict(run).split(","):
            if not reason or reason == "candidate":
                continue
            counts[reason] = counts.get(reason, 0) + 1
    return counts


def classify_next_step(runs: list[dict[str, Any]]) -> str:
    counts = reason_counts(runs)
    if not runs:
        return "No runs were found. Re-run the guarded sweep and keep the generated sweep directory."
    if counts.get("no-mic") == len(runs) or counts.get("quiet") == len(runs):
        return (
            "The sweep did not capture usable speaker audio. Check speaker wiring, "
            "Mac microphone input, and mixer state before changing kernel code."
        )
    diagnostic_reasons = (
        "tas-reinit-missing",
        "threshold-frame-missing",
        "threshold-frame-packet",
        "threshold-frame-threshold",
        "dma_op_mode-mismatch",
        "max_tx_thres-mismatch",
        "max_rx_thres-mismatch",
    )
    if any(counts.get(reason, 0) for reason in diagnostic_reasons):
        return (
            "Diagnostic evidence is missing or mismatched. Boot the current "
            "legacy-DMA image with FASTBOOT_BOOT=1 and inspect the run's "
            "remote-cmdline-check.txt, audio-register-events.txt, and sysfs logs."
        )
    dma = dma_health(runs)
    if dma.get("status") == "irq-masked":
        return (
            "DMA period callbacks were not observed and DMA IRQs appear masked. "
            "Inspect omap-dma irq_mask/irqenable_l1 in the best run before changing "
            "TAS5713 or McBSP framing."
        )
    if dma.get("status") == "missing-callbacks":
        return (
            "DMA start/stop diagnostics ran, but no cyclic period callbacks were "
            "counted. Continue in the OMAP SDMA IRQ/service path before treating "
            "the distorted audio as a codec or I2S-format problem."
        )
    kernel_reasons = ("xrun", "sync", "alsa-error", "dma-error", "codec-error")
    if any(counts.get(reason, 0) for reason in kernel_reasons):
        return (
            "Kernel-visible audio faults were logged. Inspect audio-kernel-events.txt "
            "and continue in the McBSP/SDMA fault path before trusting mic metrics."
        )
    quality_reasons = ("flutter", "dropout", "pumping", "freq", "harmonic", "clip")
    if any(counts.get(reason, 0) for reason in quality_reasons):
        dma = dma_health(runs)
        pcm = pcm_progress_health(runs)
        mcbsp = mcbsp_stop_health(runs)
        tas = tas571x_health(runs)
        if mcbsp.get("status") == "stop-irq-pending":
            return (
                "Captured audio is distorted and McBSP stop-state shows pending "
                "IRQ status. Inspect mcbsp_stop irq/fifo fields before changing "
                "TAS5713 state."
            )
        if tas.get("status") == "codec-error-latched":
            return (
                "Captured audio is distorted and TAS5713 ERR latched before stream "
                "mute. Inspect TAS5713 pre-mute registers and codec power/format "
                "sequencing before changing DMA timing."
            )
        if pcm.get("status") == "stalled-hwptr":
            return (
                "Captured audio is distorted and ALSA hw_ptr did not advance during "
                "RUNNING samples. Continue in DMA/McBSP data movement before treating "
                "this as a codec or I2S-format problem."
            )
        if pcm.get("status") in ("no-active-samples", "insufficient-samples"):
            return (
                "Captured audio is distorted, but PCM progress evidence is too weak. "
                "Repeat the module-reload probe and inspect aplay.log status samples "
                "before changing kernel code."
            )
        if dma.get("status") == "callbacks-present":
            if pcm.get("status") == "advancing":
                return (
                    "DMA cyclic callbacks and ALSA hw_ptr progress were both observed, "
                    "but captured output is still distorted. Prioritize McBSP framing/"
                    "FIFO timing and TAS5713 state over basic DMA service."
                )
            return (
                "DMA cyclic callbacks were counted, but captured output is still "
                "distorted. Prioritize McBSP framing/FIFO timing and TAS5713 state "
                "over basic DMA IRQ service."
            )
        return (
            "The diagnostic paths ran, but captured output is still distorted. "
            "Compare the best run's McBSP/DMA fields against the old 3.x path and "
            "iterate on FIFO/DMA timing."
        )
    return "No candidate was found. Inspect the top-ranked run and its verdict-specific logs."


def triage(runs: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(runs, key=sort_key)
    candidates = [run for run in ordered if verdict(run) == "candidate"]
    best = ordered[0] if ordered else None
    result: dict[str, Any] = {
        "run_count": len(runs),
        "candidate_count": len(candidates),
        "reason_counts": reason_counts(runs),
        "best_run": best.get("run") if isinstance(best, dict) else None,
        "best_verdict": verdict(best) if isinstance(best, dict) else None,
        "dma_health": dma_health(runs),
        "pcm_progress": pcm_progress_health(runs),
        "mcbsp_stop": mcbsp_stop_health(runs),
        "tas571x": tas571x_health(runs),
        "next_step": classify_next_step(runs),
    }
    if isinstance(best, dict):
        result["best_settings"] = recommended_settings(best)
        result["best_retest_command"] = retest_command(best)
        best_module_retest = module_retest_command(best)
        if best_module_retest:
            result["best_module_retest_command"] = best_module_retest
    if candidates:
        candidate = candidates[0]
        candidate_module_retest = module_retest_command(candidate)
        result.update(
            {
                "status": "candidate",
                "candidate_run": candidate.get("run"),
                "candidate_env_cv": metric(candidate, "envelope_cv_25ms"),
                "candidate_env_improvement_x": env_improvement(candidate),
                "candidate_settings": recommended_settings(candidate),
                "candidate_retest_command": retest_command(candidate),
                "next_step": (
                    "Listen to the top candidate and, if it sounds clean, promote "
                    "that mode/period/threshold combination into the default audio path."
                ),
            }
        )
        if candidate_module_retest:
            result["candidate_module_retest_command"] = candidate_module_retest
    else:
        result["status"] = "needs-investigation"
    return result


def fmt_float(value: Any) -> str:
    return f"{value:.4g}" if isinstance(value, (int, float)) and not math.isnan(float(value)) else ""


def print_text(result: dict[str, Any]) -> None:
    print(f"status: {result['status']}")
    print(f"runs: {result['run_count']} candidates: {result['candidate_count']}")
    if result.get("candidate_run"):
        print(
            "candidate: "
            f"{result['candidate_run']} "
            f"env_cv={fmt_float(result.get('candidate_env_cv'))} "
            f"env_x={fmt_float(result.get('candidate_env_improvement_x'))}"
        )
        settings = result.get("candidate_settings")
        if isinstance(settings, dict) and settings:
            parts = [f"{key}={settings[key]}" for key in sorted(settings)]
            print("settings: " + " ".join(parts))
        print("retest: " + str(result.get("candidate_retest_command", "")))
        if result.get("candidate_module_retest_command"):
            print("module_retest: " + str(result["candidate_module_retest_command"]))
    elif result.get("best_run"):
        print(f"best_run: {result['best_run']} verdict={result.get('best_verdict')}")
        settings = result.get("best_settings")
        if isinstance(settings, dict) and settings:
            parts = [f"{key}={settings[key]}" for key in sorted(settings)]
            print("settings: " + " ".join(parts))
        print("retest: " + str(result.get("best_retest_command", "")))
        if result.get("best_module_retest_command"):
            print("module_retest: " + str(result["best_module_retest_command"]))
    counts = result.get("reason_counts", {})
    if isinstance(counts, dict) and counts:
        parts = [f"{key}={counts[key]}" for key in sorted(counts)]
        print("reasons: " + " ".join(parts))
    dma = result.get("dma_health", {})
    if isinstance(dma, dict) and dma.get("status"):
        print(f"dma: {dma.get('status')} {dma.get('summary', '')}".rstrip())
    pcm = result.get("pcm_progress", {})
    if isinstance(pcm, dict) and pcm.get("status"):
        print(f"pcm: {pcm.get('status')} {pcm.get('summary', '')}".rstrip())
    mcbsp = result.get("mcbsp_stop", {})
    if isinstance(mcbsp, dict) and mcbsp.get("status"):
        print(f"mcbsp: {mcbsp.get('status')} {mcbsp.get('summary', '')}".rstrip())
    tas = result.get("tas571x", {})
    if isinstance(tas, dict) and tas.get("status"):
        print(f"tas571x: {tas.get('status')} {tas.get('summary', '')}".rstrip())
    print("next: " + str(result["next_step"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", help="sweep-summary.json or sweep directory")
    parser.add_argument("--json", action="store_true", help="emit JSON triage")
    args = parser.parse_args()

    result = triage(load_runs(args.summary))
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
