#!/usr/bin/env python3
"""Summarize Nexus Q audio probe run directories.

The guarded probe writes one directory per playback attempt. This script ranks
those directories using microphone-capture metrics when available, with the
flutter-oriented envelope coefficient of variation as the primary signal.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from typing import Any


DEFAULT_BASELINE = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "artifacts",
        "audio-baselines",
        "jun12-bad-capture-expected-440.json",
    )
)

METRIC_FILES = (
    ("mic", "mic-capture-analysis.json"),
    ("source", "source-wav-analysis.json"),
)

KERNEL_EVENT_FILES = (
    "audio-kernel-events.txt",
    "audio-register-events.txt",
    "aplay.log",
)
ORDER_EVENT_FILES = (
    "aplay.log",
    "dmesg-delta.txt",
    "audio-kernel-events.txt",
    "audio-register-events.txt",
)

KERNEL_FLAG_PATTERNS = (
    ("xrun", re.compile(r"\b(?:xrun|underrun|overrun|underflow|overflow|XUNDFL|RUNDFL)\b", re.I)),
    ("sync", re.compile(r"\b(?:XSYNC|RSYNC|sync error|frame sync)\b", re.I)),
    ("alsa-error", re.compile(r"\bALSA\b.*\berror\b|\berror\b.*\bALSA\b", re.I)),
    ("codec-error", re.compile(r"\b(?:tas571|TAS571)\S*.*\berror\b|\berror\b.*\b(?:tas571|TAS571)", re.I)),
    ("dma-error", re.compile(r"\b(?:omap-dma|dma)\S*.*\berror\b|\berror\b.*\b(?:omap-dma|dma)", re.I)),
)

DMA_CYCLIC_PATTERN = re.compile(
    r"nq cyclic .*?\bdir=(?P<dir>\d+)\s+sig=(?P<sig>\d+)\s+"
    r"ccr=(?P<ccr>0x[0-9a-fA-F]+)\s+csdp=(?P<csdp>0x[0-9a-fA-F]+)\s+"
    r"cicr=(?P<cicr>0x[0-9a-fA-F]+)(?:\s+clnk=(?P<clnk>0x[0-9a-fA-F]+))?.*?\ben=(?P<en>\d+)\s+"
    r"fn=(?P<fn>\d+)\s+fi=(?P<fi>-?\d+)\s+es=(?P<es>\d+)\s+"
    r"burst=(?P<burst>\d+)"
)

DMA_REG_PATTERN = re.compile(
    r"nq dma-(?P<phase>load|start|stopping|stopped) .*?\bch=(?P<ch>\d+)\s+"
    r"sig=(?P<sig>\d+)\s+dir=(?P<dir>\d+)\s+sgidx=(?P<sgidx>\d+)\s+"
    r"ccr=(?P<ccr>0x[0-9a-fA-F]+)\s+csdp=(?P<csdp>0x[0-9a-fA-F]+)\s+"
    r"cicr=(?P<cicr>0x[0-9a-fA-F]+)\s+csr=(?P<csr>0x[0-9a-fA-F]+)\s+"
    r"cen=(?P<cen>\d+)\s+cfn=(?P<cfn>\d+)\s+"
    r"cssa=(?P<cssa>0x[0-9a-fA-F]+)\s+cdsa=(?P<cdsa>0x[0-9a-fA-F]+)\s+"
    r"csei=(?P<csei>0x[0-9a-fA-F]+)\s+csfi=(?P<csfi>0x[0-9a-fA-F]+)\s+"
    r"cdei=(?P<cdei>0x[0-9a-fA-F]+)\s+cdfi=(?P<cdfi>0x[0-9a-fA-F]+)\s+"
    r"clnk=(?P<clnk>0x[0-9a-fA-F]+)\s+cdac=(?P<cdac>0x[0-9a-fA-F]+)"
    r"(?:\s+irq_count=(?P<irq_count>\d+)\s+irq_mask=(?P<irq_mask>0x[0-9a-fA-F]+)"
    r"\s+irqenable_l1=(?P<irqenable_l1>0x[0-9a-fA-F]+)"
    r"\s+irqstatus_l1=(?P<irqstatus_l1>0x[0-9a-fA-F]+))?"
)

DMA_IRQ_PATTERN = re.compile(
    r"nq dma-irq .*?\bch=(?P<ch>\d+)\s+sig=(?P<sig>\d+)\s+"
    r"dir=(?P<dir>\d+)\s+count=(?P<count>\d+)\s+"
    r"status=(?P<status>0x[0-9a-fA-F]+)\s+"
    r"ccr=(?P<ccr>0x[0-9a-fA-F]+)\s+csr=(?P<csr>0x[0-9a-fA-F]+)\s+"
    r"cen=(?P<cen>\d+)\s+cfn=(?P<cfn>\d+)\s+"
    r"cssa=(?P<cssa>0x[0-9a-fA-F]+)\s+cdsa=(?P<cdsa>0x[0-9a-fA-F]+)\s+"
    r"cdac=(?P<cdac>0x[0-9a-fA-F]+)\s+clnk=(?P<clnk>0x[0-9a-fA-F]+)"
    r"(?:\s+irq_mask=(?P<irq_mask>0x[0-9a-fA-F]+)"
    r"\s+irqenable_l1=(?P<irqenable_l1>0x[0-9a-fA-F]+)"
    r"\s+irqstatus_l1=(?P<irqstatus_l1>0x[0-9a-fA-F]+))?"
)

DMESG_TIME_PATTERN = re.compile(r"\[\s*(?P<time>\d+\.\d+)\]")

TAS571X_REG_PATTERN = re.compile(
    r"nq tas571x (?P<phase>\S+)\s+(?P<name>[a-z0-9_]+)"
    r"\[(?P<reg>0x[0-9a-fA-F]+)\]=(?P<value>0x[0-9a-fA-F]+)"
)

MCBSP_REG_PATTERN = re.compile(
    r"\b(?P<name>DRR[12]|DXR[12]|SPCR[12]|RCR[12]|XCR[12]|SRGR[12]|PCR0|"
    r"XCCR|RCCR|THRSH[12]|IRQEN|IRQST|XBUFFSTAT|RBUFFSTAT):\s+"
    r"(?P<value>0x[0-9a-fA-F]+)"
)

STEELHEAD_AUDIO_PATTERN = re.compile(
    r"nq steelhead (?P<phase>\S+)\s+(?P<fields>.*)"
)

MCBSP_HW_PATTERN = re.compile(
    r"nq mcbsp hw\s+(?P<fields>.*)"
)

MCBSP_START_PATTERN = re.compile(
    r"nq mcbsp start\s+(?P<fields>.*)"
)
MCBSP_STOP_PATTERN = re.compile(
    r"nq mcbsp stop\s+(?P<fields>.*)"
)

TAS571X_REINIT_PATTERN = re.compile(
    r"nq tas571x legacy-stream-reinit\s+(?P<fields>.*)"
)
TAS571X_PROBE_PATTERN = re.compile(
    r"nq tas571x probe\s+(?P<fields>.*)"
)

KEY_VALUE_PATTERN = re.compile(r"(?P<key>[A-Za-z0-9_-]+)=(?P<value>\S+)")
PCM_HW_PARAMS_KEYS = {
    "access",
    "format",
    "subformat",
    "channels",
    "rate",
    "period_size",
    "buffer_size",
}
PCM_STATUS_KEYS = {
    "state",
    "owner_pid",
    "trigger_time",
    "tstamp",
    "delay",
    "avail",
    "avail_max",
    "hw_ptr",
    "appl_ptr",
}
PROC_INTERRUPTS_MATCH_PATTERN = re.compile(
    r"\b(?:mcbsp|dma|sdma|omap|tas571|audio|snd|40122000|4a056000)\b",
    re.I,
)
ORDER_EVENT_PATTERNS = (
    ("steelhead-trigger", re.compile(r"\bnq steelhead trigger\b")),
    ("tas-reinit", re.compile(r"\bnq tas571x legacy-stream-reinit\b")),
    ("tas-unmute", re.compile(r"\bnq tas571x unmute\b")),
    ("dma-load", re.compile(r"\bnq dma-load\b")),
    ("dma-start", re.compile(r"\bnq dma-start\b")),
    ("mcbsp-thr", re.compile(r"\bnq mcbsp trigger-threshold\b")),
    ("mcbsp-start", re.compile(r"\bnq mcbsp start\b")),
    ("dma-irq", re.compile(r"\bnq dma-irq\b")),
    ("tas-pre-mute", re.compile(r"\bnq tas571x pre-mute\b")),
    ("mcbsp-stop", re.compile(r"\bnq mcbsp stop\b")),
    ("dma-stopping", re.compile(r"\bnq dma-stopping\b")),
    ("dma-stopped", re.compile(r"\bnq dma-stopped\b")),
    ("aplay-exit", re.compile(r"\baplay_exit=")),
)
MULTIPLE_ORDER_EVENT_TAGS = {
    "dma-irq",
}


def read_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if isinstance(data, dict):
        return data
    return None


def read_status(run_dir: str) -> str:
    for name in ("result.txt", "sweep-status.txt"):
        path = os.path.join(run_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read().strip()
        except OSError:
            continue
        if not text:
            continue
        if name == "result.txt" and "=" in text:
            return text.split("=", 1)[1].strip()
        return text
    return ""


def parse_written_config(run_dir: str) -> dict[str, str]:
    config: dict[str, str] = {}
    path = os.path.join(run_dir, "mcbsp-sysfs-config.txt")
    try:
        lines = open(path, "r", encoding="utf-8").read().splitlines()
    except OSError:
        return config

    for line in lines:
        marker = "--- write "
        if not line.startswith(marker) or " = " not in line:
            continue
        left, value = line[len(marker) :].rsplit(" = ", 1)
        name = os.path.basename(left)
        config[name] = value
    return config


def parse_case_plan(run_dir: str) -> dict[str, str]:
    plan: dict[str, str] = {}
    path = os.path.join(run_dir, "case-plan.txt")
    try:
        lines = open(path, "r", encoding="utf-8").read().splitlines()
    except OSError:
        return plan

    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        plan[key.strip()] = value.strip()
    return plan


def parse_attr_value(attr: str, value: str) -> str:
    value = value.strip()
    if attr == "dma_op_mode":
        match = re.search(r"\[([^\]]+)\]", value)
        if match:
            return match.group(1)
    return value.split()[0] if value.split() else ""


def parse_mcbsp_sysfs(run_dir: str) -> dict[str, Any]:
    requested: dict[str, str] = {}
    actual: dict[str, str] = {}

    for name in ("mcbsp-sysfs-config.txt", "mcbsp-sysfs-before.txt", "aplay.log"):
        path = os.path.join(run_dir, name)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue

        current_attr = ""
        for line in lines:
            if line.startswith("--- "):
                current_attr = ""
                if " = " in line and line.startswith("--- write "):
                    left, value = line[len("--- write ") :].rsplit(" = ", 1)
                    attr = os.path.basename(left)
                    requested[attr] = value.strip()
                    continue
                path_part = line[len("--- ") :]
                if path_part.startswith("read "):
                    path_part = path_part[len("read ") :]
                attr = os.path.basename(path_part)
                if attr in ("dma_op_mode", "max_tx_thres", "max_rx_thres"):
                    current_attr = attr
                continue

            if not current_attr or not line.strip() or line.startswith("==="):
                continue
            actual[current_attr] = parse_attr_value(current_attr, line)
            current_attr = ""

    return {
        "requested": requested,
        "actual": actual,
    }


def parse_dma_cyclic(run_dir: str) -> dict[str, str]:
    for name in ("audio-kernel-events.txt", "audio-register-events.txt", "aplay.log"):
        path = os.path.join(run_dir, name)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        for line in lines:
            match = DMA_CYCLIC_PATTERN.search(line)
            if match:
                return match.groupdict()
    return {}


def parse_dma_regs(run_dir: str, phase: str) -> dict[str, str]:
    fallback: dict[str, str] = {}
    for name in ("audio-kernel-events.txt", "audio-register-events.txt", "aplay.log"):
        path = os.path.join(run_dir, name)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        for line in lines:
            match = DMA_REG_PATTERN.search(line)
            if not match:
                continue
            fields = match.groupdict()
            if fields["phase"] == phase:
                return fields
            if not fallback:
                fallback = fields
    return fallback


def parse_dma_irqs(run_dir: str) -> dict[str, Any]:
    latest: dict[str, str] = {}
    events: list[dict[str, str]] = []
    intervals_ms: list[float] = []
    seen: set[tuple[str, str, str]] = set()

    for name in ("audio-kernel-events.txt", "audio-register-events.txt", "aplay.log"):
        path = os.path.join(run_dir, name)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        for line in lines:
            match = DMA_IRQ_PATTERN.search(line)
            if not match:
                continue
            fields = match.groupdict()
            time_match = DMESG_TIME_PATTERN.search(line)
            if time_match:
                fields["time_s"] = time_match.group("time")
            key = (fields.get("count", ""), fields.get("status", ""), fields.get("time_s", ""))
            if key in seen:
                continue
            seen.add(key)
            latest = fields
            events.append(fields)

    for prev, cur in zip(events, events[1:]):
        prev_time = prev.get("time_s")
        cur_time = cur.get("time_s")
        if prev_time is None or cur_time is None:
            continue
        intervals_ms.append((float(cur_time) - float(prev_time)) * 1000.0)

    return {
        "latest": latest,
        "events": events,
        "intervals_ms": intervals_ms,
        "interval_avg_ms": sum(intervals_ms) / len(intervals_ms) if intervals_ms else None,
        "interval_min_ms": min(intervals_ms) if intervals_ms else None,
        "interval_max_ms": max(intervals_ms) if intervals_ms else None,
    }


def parse_mcbsp_regs(run_dir: str) -> dict[str, str]:
    latest: dict[str, str] = {}

    for name in ("audio-register-events.txt", "audio-kernel-events.txt", "aplay.log"):
        path = os.path.join(run_dir, name)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue

        for line in lines:
            match = MCBSP_REG_PATTERN.search(line)
            if not match:
                continue
            latest[match.group("name").lower()] = match.group("value")

    return latest


def parse_tas571x_regs(run_dir: str) -> dict[str, Any]:
    latest: dict[str, str] = {}
    phases: dict[str, dict[str, str]] = {}
    reinit_latest: dict[str, str] = {}
    reinit_events: list[dict[str, str]] = []
    probe_latest: dict[str, str] = {}
    probe_events: list[dict[str, str]] = []

    for name in ("audio-kernel-events.txt", "audio-register-events.txt", "aplay.log"):
        path = os.path.join(run_dir, name)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue

        for line in lines:
            probe_match = TAS571X_PROBE_PATTERN.search(line)
            if probe_match:
                fields = {
                    field.group("key"): field.group("value")
                    for field in KEY_VALUE_PATTERN.finditer(probe_match.group("fields"))
                }
                if fields:
                    probe_latest.update(fields)
                    probe_events.append(fields)
                continue

            reinit_match = TAS571X_REINIT_PATTERN.search(line)
            if reinit_match:
                fields = {
                    field.group("key"): field.group("value")
                    for field in KEY_VALUE_PATTERN.finditer(reinit_match.group("fields"))
                }
                if fields:
                    reinit_latest.update(fields)
                    reinit_events.append(fields)
                continue

            match = TAS571X_REG_PATTERN.search(line)
            if not match:
                continue
            fields = match.groupdict()
            phase = fields["phase"]
            reg_name = fields["name"]
            value = fields["value"]
            phases.setdefault(phase, {})[reg_name] = value
            latest[reg_name] = value

    return {
        "latest": latest,
        "phases": phases,
        "legacy_reinit": {
            "latest": reinit_latest,
            "events": reinit_events,
        },
        "probe": {
            "latest": probe_latest,
            "events": probe_events,
        },
    }


def parse_mcbsp_hw(run_dir: str) -> dict[str, Any]:
    latest: dict[str, str] = {}
    events: list[dict[str, str]] = []

    for name in ("audio-kernel-events.txt", "audio-register-events.txt", "aplay.log"):
        path = os.path.join(run_dir, name)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue

        for line in lines:
            match = MCBSP_HW_PATTERN.search(line)
            if not match:
                continue
            fields = {
                field.group("key"): field.group("value")
                for field in KEY_VALUE_PATTERN.finditer(match.group("fields"))
            }
            if not fields:
                continue
            latest.update(fields)
            events.append(fields)

    return {
        "latest": latest,
        "events": events,
    }


def parse_mcbsp_start(run_dir: str) -> dict[str, Any]:
    latest: dict[str, str] = {}
    events: list[dict[str, str]] = []

    for name in ("audio-kernel-events.txt", "audio-register-events.txt", "aplay.log"):
        path = os.path.join(run_dir, name)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue

        for line in lines:
            match = MCBSP_START_PATTERN.search(line)
            if not match:
                continue
            fields = {
                field.group("key"): field.group("value")
                for field in KEY_VALUE_PATTERN.finditer(match.group("fields"))
            }
            if not fields:
                continue
            latest.update(fields)
            events.append(fields)

    return {
        "latest": latest,
        "events": events,
    }


def parse_mcbsp_stop(run_dir: str) -> dict[str, Any]:
    latest: dict[str, str] = {}
    events: list[dict[str, str]] = []

    for name in ("audio-kernel-events.txt", "audio-register-events.txt", "aplay.log"):
        path = os.path.join(run_dir, name)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue

        for line in lines:
            match = MCBSP_STOP_PATTERN.search(line)
            if not match:
                continue
            fields = {
                field.group("key"): field.group("value")
                for field in KEY_VALUE_PATTERN.finditer(match.group("fields"))
            }
            if not fields:
                continue
            latest.update(fields)
            events.append(fields)

    return {
        "latest": latest,
        "events": events,
    }


def parse_steelhead_audio(run_dir: str) -> dict[str, Any]:
    latest: dict[str, str] = {}
    phases: dict[str, dict[str, str]] = {}

    for name in ("audio-kernel-events.txt", "audio-register-events.txt", "aplay.log"):
        path = os.path.join(run_dir, name)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue

        for line in lines:
            match = STEELHEAD_AUDIO_PATTERN.search(line)
            if not match:
                continue
            fields = {
                field.group("key"): field.group("value")
                for field in KEY_VALUE_PATTERN.finditer(match.group("fields"))
            }
            if not fields:
                continue
            phase = match.group("phase")
            phases.setdefault(phase, {}).update(fields)
            latest.update(fields)

    return {
        "latest": latest,
        "phases": phases,
    }


def parse_kernel_events(run_dir: str) -> dict[str, Any]:
    flags: list[str] = []
    matches: list[str] = []

    for name in KERNEL_EVENT_FILES:
        path = os.path.join(run_dir, name)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        for line in lines:
            for flag, pattern in KERNEL_FLAG_PATTERNS:
                if not pattern.search(line):
                    continue
                if flag not in flags:
                    flags.append(flag)
                if len(matches) < 20:
                    matches.append(f"{name}: {line}")

    return {
        "flags": flags,
        "count": len(matches),
        "matches": matches,
    }


def proc_snapshot_marker_path(line: str) -> str:
    if not line.startswith("--- "):
        return ""
    return line[4:].strip().split(None, 1)[0]


def parse_int_field(fields: dict[str, str], name: str) -> int | None:
    value = fields.get(name)
    if value is None:
        return None
    try:
        return int(value, 0)
    except ValueError:
        return None


def parse_pcm_hw_params(run_dir: str) -> dict[str, str]:
    latest: dict[str, str] = {}
    current: dict[str, str] | None = None

    path = os.path.join(run_dir, "aplay.log")
    try:
        lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return latest

    def finish_current() -> None:
        nonlocal current, latest
        if current:
            latest.update(current)
        current = None

    for line in lines:
        if line.startswith("--- "):
            finish_current()
            if proc_snapshot_marker_path(line).endswith("/hw_params"):
                current = {}
            continue

        if current is None or ": " not in line:
            continue

        key, value = line.split(": ", 1)
        if key in PCM_HW_PARAMS_KEYS:
            current[key] = value.strip()

    finish_current()
    return latest


def parse_pcm_status(run_dir: str) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    samples: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    path = os.path.join(run_dir, "aplay.log")
    try:
        lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return latest

    def finish_current() -> None:
        nonlocal current
        if current:
            samples.append(dict(current))
            latest.update(current)
        current = None

    for line in lines:
        if line.startswith("pcm_status_wait_state="):
            for field in KEY_VALUE_PATTERN.finditer(line):
                latest[field.group("key")] = field.group("value")
            continue

        if line.startswith("--- "):
            finish_current()
            path = proc_snapshot_marker_path(line)
            if path.endswith("/status"):
                current = {}
                for field in KEY_VALUE_PATTERN.finditer(line):
                    current[field.group("key")] = field.group("value")
            continue

        if current is None or ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        normalized_key = key.replace(" ", "_")
        if normalized_key in PCM_STATUS_KEYS:
            current[normalized_key] = value.strip()

    finish_current()
    if samples:
        latest["samples"] = samples
        latest["sample_count"] = len(samples)
        first_hw = parse_int_field(samples[0], "hw_ptr")
        last_hw = parse_int_field(samples[-1], "hw_ptr")
        first_appl = parse_int_field(samples[0], "appl_ptr")
        last_appl = parse_int_field(samples[-1], "appl_ptr")
        if first_hw is not None:
            latest["first_hw_ptr"] = str(first_hw)
        if last_hw is not None:
            latest["last_hw_ptr"] = str(last_hw)
        if first_hw is not None and last_hw is not None:
            latest["hw_ptr_delta"] = str(last_hw - first_hw)
        if first_appl is not None:
            latest["first_appl_ptr"] = str(first_appl)
        if last_appl is not None:
            latest["last_appl_ptr"] = str(last_appl)
        if first_appl is not None and last_appl is not None:
            latest["appl_ptr_delta"] = str(last_appl - first_appl)
    return latest


def parse_interrupt_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped or ":" not in stripped:
        return None
    irq, rest = stripped.split(":", 1)
    irq = irq.strip()
    if not irq:
        return None

    fields = rest.split()
    counts: list[int] = []
    label_index = 0
    for index, field in enumerate(fields):
        try:
            counts.append(int(field, 10))
        except ValueError:
            label_index = index
            break
    else:
        label_index = len(fields)

    if not counts:
        return None

    label = " ".join(fields[label_index:])
    if not PROC_INTERRUPTS_MATCH_PATTERN.search(f"{irq} {label}"):
        return None

    return {
        "irq": irq,
        "count": sum(counts),
        "label": label,
        "key": f"{irq}:{label}",
    }


def parse_interrupt_snapshot_lines(lines: list[str], sample: str) -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    for line in lines:
        parsed = parse_interrupt_line(line)
        if not parsed:
            continue
        key = str(parsed.pop("key"))
        entries[key] = parsed
    return {
        "sample": sample,
        "entries": entries,
    }


def interrupt_deltas(
    first: dict[str, Any] | None,
    last: dict[str, Any] | None,
) -> tuple[dict[str, int], int]:
    if not first or not last:
        return {}, 0
    first_entries = first.get("entries", {})
    last_entries = last.get("entries", {})
    if not isinstance(first_entries, dict) or not isinstance(last_entries, dict):
        return {}, 0

    deltas: dict[str, int] = {}
    for key, last_entry in last_entries.items():
        if key not in first_entries:
            continue
        first_entry = first_entries[key]
        if not isinstance(first_entry, dict) or not isinstance(last_entry, dict):
            continue
        try:
            delta = int(last_entry.get("count", 0)) - int(first_entry.get("count", 0))
        except (TypeError, ValueError):
            continue
        if delta > 0:
            deltas[key] = delta

    return deltas, sum(deltas.values())


def summarize_interrupt_deltas(deltas: dict[str, int], limit: int = 3) -> str:
    parts = []
    for key, delta in sorted(deltas.items(), key=lambda item: item[1], reverse=True)[:limit]:
        label = key
        if ":" in label:
            irq, rest = label.split(":", 1)
            tail = rest.split()[-1] if rest.split() else irq
            label = tail if tail else irq
        parts.append(f"{label}:{delta}")
    return ",".join(parts)


def parse_proc_interrupts(run_dir: str) -> dict[str, Any]:
    active_samples: list[dict[str, Any]] = []
    before_snapshot: dict[str, Any] | None = None
    after_snapshot: dict[str, Any] | None = None

    for label, filename in (("before", "interrupts-before.txt"), ("after", "interrupts-after.txt")):
        path = os.path.join(run_dir, filename)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue
        snapshot = parse_interrupt_snapshot_lines(lines, label)
        if label == "before":
            before_snapshot = snapshot
        else:
            after_snapshot = snapshot

    path = os.path.join(run_dir, "aplay.log")
    try:
        lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        lines = []

    current_sample = ""
    current_lines: list[str] = []

    def finish_current() -> None:
        nonlocal current_sample, current_lines
        if current_sample:
            snapshot = parse_interrupt_snapshot_lines(current_lines, current_sample)
            if snapshot["entries"]:
                active_samples.append(snapshot)
        current_sample = ""
        current_lines = []

    for line in lines:
        if line.startswith("--- /proc/interrupts"):
            finish_current()
            fields = {
                field.group("key"): field.group("value")
                for field in KEY_VALUE_PATTERN.finditer(line)
            }
            current_sample = fields.get("sample", str(len(active_samples)))
            current_lines = []
            continue
        if line.startswith("--- ") or line.startswith("==="):
            finish_current()
            continue
        if current_sample:
            current_lines.append(line)

    finish_current()

    active_deltas, active_total = interrupt_deltas(
        active_samples[0] if active_samples else None,
        active_samples[-1] if active_samples else None,
    )
    before_after_deltas, before_after_total = interrupt_deltas(before_snapshot, after_snapshot)

    return {
        "samples": active_samples,
        "sample_count": len(active_samples),
        "active_deltas": active_deltas,
        "active_delta_total": active_total,
        "active_top": summarize_interrupt_deltas(active_deltas),
        "before": before_snapshot or {},
        "after": after_snapshot or {},
        "before_after_deltas": before_after_deltas,
        "before_after_delta_total": before_after_total,
        "before_after_top": summarize_interrupt_deltas(before_after_deltas),
    }


def dmesg_time_s(line: str) -> float | None:
    match = DMESG_TIME_PATTERN.search(line)
    if not match:
        return None
    try:
        return float(match.group("time"))
    except ValueError:
        return None


def compact_order_sequence(events: list[dict[str, Any]]) -> str:
    tags: list[str] = []
    for event in events:
        tag = str(event.get("tag", ""))
        if tag and tag not in tags:
            tags.append(tag)
    return ">".join(tags)


def first_event_by_tag(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for event in events:
        tag = str(event.get("tag", ""))
        if tag and tag not in found:
            found[tag] = event
    return found


def delta_ms(first: dict[str, Any] | None, second: dict[str, Any] | None) -> float | None:
    if not first or not second:
        return None
    first_time = first.get("time_s")
    second_time = second.get("time_s")
    if not isinstance(first_time, (int, float)) or not isinstance(second_time, (int, float)):
        return None
    return (float(second_time) - float(first_time)) * 1000.0


def parse_event_order(run_dir: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    order = 0

    for source in ORDER_EVENT_FILES:
        source_events: list[dict[str, Any]] = []
        seen_tags: set[str] = set()
        path = os.path.join(run_dir, source)
        try:
            lines = open(path, "r", encoding="utf-8", errors="replace").read().splitlines()
        except OSError:
            continue

        for lineno, line in enumerate(lines, start=1):
            for tag, pattern in ORDER_EVENT_PATTERNS:
                if not pattern.search(line):
                    continue
                if tag in seen_tags and tag not in MULTIPLE_ORDER_EVENT_TAGS:
                    continue
                seen_tags.add(tag)
                event = {
                    "tag": tag,
                    "source": source,
                    "lineno": lineno,
                    "order": order,
                    "line": line,
                }
                time_s = dmesg_time_s(line)
                if time_s is not None:
                    event["time_s"] = time_s
                source_events.append(event)
                order += 1
                break

        if source_events and any(event.get("tag") != "aplay-exit" for event in source_events):
            events = source_events
            break
        if source_events and not events:
            events = source_events

    by_tag = first_event_by_tag(events)
    first_dma_irq = None
    mcbsp_start = by_tag.get("mcbsp-start")
    for event in events:
        if event.get("tag") != "dma-irq":
            continue
        if not mcbsp_start:
            first_dma_irq = event
            break
        event_time = event.get("time_s")
        mcbsp_time = mcbsp_start.get("time_s")
        if (
            isinstance(event_time, (int, float))
            and isinstance(mcbsp_time, (int, float))
            and event_time < mcbsp_time
        ):
            continue
        first_dma_irq = event
        break

    return {
        "events": events,
        "sequence": compact_order_sequence(events),
        "tas_unmute_to_dma_ms": delta_ms(by_tag.get("tas-unmute"), by_tag.get("dma-start")),
        "dma_to_mcbsp_ms": delta_ms(by_tag.get("dma-start"), by_tag.get("mcbsp-start")),
        "mcbsp_to_dmairq_ms": delta_ms(by_tag.get("mcbsp-start"), first_dma_irq),
    }


def parse_dir_hint(name: str) -> dict[str, str]:
    hint: dict[str, str] = {}
    if "threshold" in name:
        hint["dma_op_mode"] = "threshold"
        tail = name.rsplit("threshold-", 1)
        if len(tail) == 2 and tail[1].isdigit():
            hint["max_tx_thres"] = tail[1]
    elif "element" in name:
        hint["dma_op_mode"] = "element"
    return hint


def collect_run(run_dir: str, root: str, prefix: str = "") -> dict[str, Any] | None:
    metrics_source = ""
    metrics: dict[str, Any] | None = None
    for source, name in METRIC_FILES:
        metrics = read_json(os.path.join(run_dir, name))
        if metrics is not None:
            metrics_source = source
            break
    if metrics is None:
        return None

    rel = os.path.relpath(run_dir, root)
    if rel == ".":
        rel = os.path.basename(os.path.abspath(run_dir))
    elif prefix:
        rel = os.path.join(prefix, rel)

    hint = parse_dir_hint(os.path.basename(run_dir))
    written = parse_written_config(run_dir)
    sysfs = parse_mcbsp_sysfs(run_dir)
    actual = sysfs["actual"]
    requested = dict(hint)
    requested.update(written)
    requested.update(sysfs["requested"])

    return {
        "run": rel,
        "path": run_dir,
        "status": read_status(run_dir),
        "metrics_source": metrics_source,
        "dma_op_mode": actual.get("dma_op_mode", requested.get("dma_op_mode", "")),
        "max_tx_thres": actual.get("max_tx_thres", requested.get("max_tx_thres", "")),
        "case_plan": parse_case_plan(run_dir),
        "mcbsp_sysfs": sysfs,
        "mcbsp_hw": parse_mcbsp_hw(run_dir),
        "mcbsp_start": parse_mcbsp_start(run_dir),
        "mcbsp_stop": parse_mcbsp_stop(run_dir),
        "mcbsp_regs": parse_mcbsp_regs(run_dir),
        "dma_cyclic": parse_dma_cyclic(run_dir),
        "dma_start": parse_dma_regs(run_dir, "start"),
        "dma_stop": parse_dma_regs(run_dir, "stopped"),
        "dma_irq": parse_dma_irqs(run_dir),
        "steelhead_audio": parse_steelhead_audio(run_dir),
        "tas571x": parse_tas571x_regs(run_dir),
        "pcm_hw_params": parse_pcm_hw_params(run_dir),
        "pcm_status": parse_pcm_status(run_dir),
        "proc_interrupts": parse_proc_interrupts(run_dir),
        "event_order": parse_event_order(run_dir),
        "kernel_events": parse_kernel_events(run_dir),
        "metrics": metrics,
    }


def find_runs(paths: list[str]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    multi_root = len(paths) > 1
    for root in paths:
        root = os.path.abspath(root)
        direct = collect_run(root, root)
        if direct is not None:
            runs.append(direct)
            continue

        prefix = os.path.basename(root) if multi_root else ""
        for dirpath, dirnames, filenames in os.walk(root):
            if any(name in filenames for _, name in METRIC_FILES):
                run = collect_run(dirpath, root, prefix)
                if run is not None:
                    runs.append(run)
                dirnames[:] = []
    return runs


def metric(run: dict[str, Any], name: str) -> float:
    value = run["metrics"].get(name)
    if isinstance(value, (int, float)):
        return float(value)
    return math.nan


def status_ok(run: dict[str, Any]) -> bool:
    status = run.get("status", "")
    return status in ("", "0")


def run_basename(run: dict[str, Any]) -> str:
    return os.path.basename(str(run.get("run", "")))


def is_threshold_frame_run(run: dict[str, Any]) -> bool:
    return "threshold-frame" in run_basename(run)


def latest_fields(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    latest = value.get("latest")
    return latest if isinstance(latest, dict) else {}


def tas571x_reinit_fields(run: dict[str, Any]) -> dict[str, str]:
    tas571x = run.get("tas571x", {})
    if not isinstance(tas571x, dict):
        return {}
    return latest_fields(tas571x.get("legacy_reinit"))


def quality_analysis(
    run: dict[str, Any],
    baseline: dict[str, Any] | None,
    max_env_cv: float,
    max_env_low_pct: float,
    max_env_range_db: float,
    max_freq_error_pct: float,
    max_harmonic_ratio: float,
    max_clip_pct: float,
    min_mic_rms: float,
) -> dict[str, Any]:
    env = metric(run, "envelope_cv_25ms")
    env_low_pct = metric(run, "envelope_low_pct_25ms")
    env_range_db = metric(run, "envelope_peak_to_trough_db_25ms")
    freq_err = abs(metric(run, "zero_cross_freq_error_pct"))
    harmonic = metric(run, "harmonic_power_ratio_2_8")
    clipped = metric(run, "clipped_pct")
    mic_rms = metric(run, "rms")
    kernel_events = run.get("kernel_events", {})
    kernel_flags = kernel_events.get("flags") if isinstance(kernel_events, dict) else []
    sysfs = run.get("mcbsp_sysfs", {})
    requested = sysfs.get("requested", {}) if isinstance(sysfs, dict) else {}
    actual = sysfs.get("actual", {}) if isinstance(sysfs, dict) else {}
    mcbsp_hw = latest_fields(run.get("mcbsp_hw"))
    mcbsp_start = latest_fields(run.get("mcbsp_start"))
    tas_reinit = tas571x_reinit_fields(run)
    reasons = []

    if not status_ok(run):
        reasons.append("failed")
    if kernel_flags:
        reasons.extend(str(flag) for flag in kernel_flags)
    for attr in ("dma_op_mode", "max_tx_thres", "max_rx_thres"):
        req = requested.get(attr)
        act = actual.get(attr)
        if req and act and req != act:
            reasons.append(f"{attr}-mismatch")
    if tas_reinit.get("override") != "1" or tas_reinit.get("keep_mclk") != "1":
        reasons.append("tas-reinit-missing")
    if is_threshold_frame_run(run):
        if mcbsp_hw.get("legacy_threshold_frame") != "1":
            reasons.append("threshold-frame-missing")
        if mcbsp_hw.get("pkt_size") != "0":
            reasons.append("threshold-frame-packet")
        if (
            not mcbsp_hw.get("period_words")
            or not mcbsp_hw.get("threshold_words")
            or mcbsp_hw.get("period_words") != mcbsp_hw.get("threshold_words")
        ):
            reasons.append("threshold-frame-threshold")
    if run["metrics_source"] != "mic":
        reasons.append("no-mic")
    elif math.isnan(mic_rms) or mic_rms < min_mic_rms:
        reasons.append("quiet")
    if math.isnan(env):
        reasons.append("no-env")
    elif env > max_env_cv:
        reasons.append("flutter")
    if not math.isnan(env_low_pct) and env_low_pct > max_env_low_pct:
        reasons.append("dropout")
    if not math.isnan(env_range_db) and env_range_db > max_env_range_db:
        reasons.append("pumping")
    if math.isnan(freq_err):
        reasons.append("no-freq")
    elif freq_err > max_freq_error_pct:
        reasons.append("freq")
    if math.isnan(harmonic):
        reasons.append("no-harm")
    elif harmonic > max_harmonic_ratio:
        reasons.append("harmonic")
    if math.isnan(clipped):
        reasons.append("no-clip")
    elif clipped > max_clip_pct:
        reasons.append("clip")

    baseline_env = None
    env_improvement = None
    if baseline is not None:
        value = baseline.get("envelope_cv_25ms")
        if isinstance(value, (int, float)) and value > 0 and not math.isnan(env):
            baseline_env = float(value)
            env_improvement = baseline_env / env if env > 0 else math.inf

    verdict = "candidate" if not reasons else ",".join(reasons)
    return {
        "verdict": verdict,
        "env_improvement_x": env_improvement,
        "baseline_env_cv_25ms": baseline_env,
        "kernel_flags": kernel_flags,
        "mcbsp_requested": requested,
        "mcbsp_actual": actual,
        "mcbsp_hw": mcbsp_hw,
        "mcbsp_start": mcbsp_start,
        "tas571x_reinit": tas_reinit,
        "limits": {
            "max_env_cv": max_env_cv,
            "max_env_low_pct": max_env_low_pct,
            "max_env_range_db": max_env_range_db,
            "max_freq_error_pct": max_freq_error_pct,
            "max_harmonic_ratio": max_harmonic_ratio,
            "max_clip_pct": max_clip_pct,
            "min_mic_rms": min_mic_rms,
        },
    }


def rank_key(run: dict[str, Any]) -> tuple[int, int, int, float, float, float]:
    failed = 0 if status_ok(run) else 1
    has_mic = 0 if run["metrics_source"] == "mic" else 1
    analysis = run.get("analysis")
    verdict = analysis.get("verdict") if isinstance(analysis, dict) else None
    non_candidate = 0 if verdict in (None, "candidate") else 1
    env = metric(run, "envelope_cv_25ms")
    freq_err = abs(metric(run, "zero_cross_freq_error_pct"))
    harmonic = metric(run, "harmonic_power_ratio_2_8")
    return (
        failed,
        has_mic,
        non_candidate,
        env if not math.isnan(env) else math.inf,
        freq_err if not math.isnan(freq_err) else math.inf,
        harmonic if not math.isnan(harmonic) else math.inf,
    )


def fmt(value: float, digits: int = 4) -> str:
    if math.isnan(value):
        return ""
    return f"{value:.{digits}g}"


def fmt_optional(value: Any, digits: int = 4) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return fmt(float(value), digits)


def first_token(value: Any) -> str:
    tokens = str(value).split()
    return tokens[0] if tokens else ""


def print_table(runs: list[dict[str, Any]]) -> None:
    headers = [
        "rank",
        "run",
        "status",
        "src",
        "pcm_fmt",
        "pcm_rate",
        "pcm_ch",
        "period",
        "buffer",
        "pcm_state",
        "delay",
        "avail",
        "avail_max",
        "hwptr",
        "applptr",
        "samples",
        "hwd",
        "appd",
        "mode",
        "tx",
        "mhw",
        "frame",
        "pwords",
        "pkt",
        "thw",
        "reinit",
        "kmclk",
        "tmute",
        "cpwr",
        "sig",
        "burst_bits",
        "tx_burst",
        "trig_thr",
        "plan_bclk",
        "ccr",
        "csdp",
        "rccr",
        "rcsdp",
        "rclnk",
        "icnt",
        "istat",
        "icsr",
        "icdac",
        "iavg_ms",
        "imax_ms",
        "pisamp",
        "pidelta",
        "pba_delta",
        "pitop",
        "seq",
        "d2m_ms",
        "m2irq_ms",
        "scsr",
        "scdac",
        "scnt",
        "simask",
        "sistat1",
        "irqen",
        "irqst",
        "xbuf",
        "rbuf",
        "xrdy",
        "xrst",
        "rrdy",
        "rrst",
        "stirq",
        "stxbuf",
        "strbuf",
        "stspcr2",
        "thr2",
        "thr1",
        "fmt",
        "inv",
        "s16",
        "bclk",
        "bclk_ovr",
        "div",
        "mclk",
        "sdi",
        "sys2",
        "err",
        "mvol",
        "pm_sys2",
        "pm_err",
        "rms",
        "tone",
        "freq_hz",
        "err_pct",
        "env_cv",
        "low_pct",
        "range_db",
        "mod_hz",
        "mod_score",
        "env_x",
        "harm_2_8",
        "clip_pct",
        "kernel",
        "verdict",
    ]
    rows = []
    for idx, run in enumerate(sorted(runs, key=rank_key), start=1):
        analysis = run.get("analysis", {})
        env_improvement = analysis.get("env_improvement_x")
        if not isinstance(env_improvement, (int, float)):
            env_improvement = math.nan
        dma = run.get("dma_cyclic", {})
        dma_start = run.get("dma_start", {})
        dma_stop = run.get("dma_stop", {})
        dma_irq = run.get("dma_irq", {})
        dma_irq_latest = dma_irq.get("latest", {}) if isinstance(dma_irq, dict) else {}
        mcbsp_hw = run.get("mcbsp_hw", {})
        mcbsp_hw_latest = mcbsp_hw.get("latest", {}) if isinstance(mcbsp_hw, dict) else {}
        mcbsp_start = run.get("mcbsp_start", {})
        mcbsp_start_latest = (
            mcbsp_start.get("latest", {}) if isinstance(mcbsp_start, dict) else {}
        )
        mcbsp_stop = run.get("mcbsp_stop", {})
        mcbsp_stop_latest = (
            mcbsp_stop.get("latest", {}) if isinstance(mcbsp_stop, dict) else {}
        )
        mcbsp_regs = run.get("mcbsp_regs", {})
        steelhead = run.get("steelhead_audio", {})
        steelhead_phases = steelhead.get("phases", {}) if isinstance(steelhead, dict) else {}
        steelhead_hw = steelhead_phases.get("hw_params", {}) if isinstance(steelhead_phases, dict) else {}
        steelhead_trigger = steelhead_phases.get("trigger", {}) if isinstance(steelhead_phases, dict) else {}
        tas571x = run.get("tas571x", {})
        tas_latest = tas571x.get("latest", {}) if isinstance(tas571x, dict) else {}
        tas_phases = tas571x.get("phases", {}) if isinstance(tas571x, dict) else {}
        tas_pre_mute = (
            tas_phases.get("pre-mute", {}) if isinstance(tas_phases, dict) else {}
        )
        tas_reinit = tas571x.get("legacy_reinit", {}) if isinstance(tas571x, dict) else {}
        tas_reinit_latest = tas_reinit.get("latest", {}) if isinstance(tas_reinit, dict) else {}
        tas_probe = tas571x.get("probe", {}) if isinstance(tas571x, dict) else {}
        tas_probe_latest = tas_probe.get("latest", {}) if isinstance(tas_probe, dict) else {}
        pcm_hw = run.get("pcm_hw_params", {})
        pcm_hw = pcm_hw if isinstance(pcm_hw, dict) else {}
        pcm_status = run.get("pcm_status", {})
        pcm_status = pcm_status if isinstance(pcm_status, dict) else {}
        proc_interrupts = run.get("proc_interrupts", {})
        proc_interrupts = proc_interrupts if isinstance(proc_interrupts, dict) else {}
        event_order = run.get("event_order", {})
        event_order = event_order if isinstance(event_order, dict) else {}
        rows.append(
            [
                str(idx),
                run["run"],
                run["status"],
                run["metrics_source"],
                pcm_hw.get("format", ""),
                first_token(pcm_hw.get("rate", "")),
                pcm_hw.get("channels", ""),
                pcm_hw.get("period_size", ""),
                pcm_hw.get("buffer_size", ""),
                pcm_status.get("state", pcm_status.get("pcm_status_wait_state", "")),
                pcm_status.get("delay", ""),
                pcm_status.get("avail", ""),
                pcm_status.get("avail_max", ""),
                pcm_status.get("hw_ptr", ""),
                pcm_status.get("appl_ptr", ""),
                str(pcm_status.get("sample_count", "")),
                str(pcm_status.get("hw_ptr_delta", "")),
                str(pcm_status.get("appl_ptr_delta", "")),
                run["dma_op_mode"],
                run["max_tx_thres"],
                mcbsp_hw_latest.get("mode", ""),
                mcbsp_hw_latest.get("legacy_threshold_frame", ""),
                mcbsp_hw_latest.get("period_words", ""),
                mcbsp_hw_latest.get("pkt_size", ""),
                mcbsp_hw_latest.get("threshold_words", ""),
                tas_reinit_latest.get("override", ""),
                tas_reinit_latest.get("keep_mclk", ""),
                tas_probe_latest.get("mute_on_trigger", ""),
                steelhead_trigger.get(
                    "codec_power_first",
                    run.get("case_plan", {}).get("codec_power_first", ""),
                ),
                dma.get("sig", ""),
                run.get("case_plan", {}).get("burst_bits", ""),
                run.get("case_plan", {}).get("mcbsp_tx_burst", ""),
                run.get("case_plan", {}).get("mcbsp_trigger_threshold", ""),
                run.get("case_plan", {}).get("bclk_fs", ""),
                dma.get("ccr", ""),
                dma.get("csdp", ""),
                dma_start.get("ccr", ""),
                dma_start.get("csdp", ""),
                dma_start.get("clnk", ""),
                dma_irq_latest.get("count", ""),
                dma_irq_latest.get("status", ""),
                dma_irq_latest.get("csr", ""),
                dma_irq_latest.get("cdac", ""),
                fmt_optional(dma_irq.get("interval_avg_ms"), 3),
                fmt_optional(dma_irq.get("interval_max_ms"), 3),
                str(proc_interrupts.get("sample_count", "")),
                str(proc_interrupts.get("active_delta_total", "")),
                str(proc_interrupts.get("before_after_delta_total", "")),
                str(proc_interrupts.get("active_top", "")),
                str(event_order.get("sequence", "")),
                fmt_optional(event_order.get("dma_to_mcbsp_ms"), 3),
                fmt_optional(event_order.get("mcbsp_to_dmairq_ms"), 3),
                dma_stop.get("csr", ""),
                dma_stop.get("cdac", ""),
                dma_stop.get("irq_count") or "",
                dma_stop.get("irq_mask") or "",
                dma_stop.get("irqstatus_l1") or "",
                mcbsp_regs.get("irqen", ""),
                mcbsp_regs.get("irqst", ""),
                mcbsp_regs.get("xbuffstat", ""),
                mcbsp_regs.get("rbuffstat", ""),
                mcbsp_start_latest.get("xready", ""),
                mcbsp_start_latest.get("xrst_reset", ""),
                mcbsp_start_latest.get("rready", ""),
                mcbsp_start_latest.get("rrst_reset", ""),
                mcbsp_stop_latest.get("irqst_before", ""),
                mcbsp_stop_latest.get("xbuffstat_before", ""),
                mcbsp_stop_latest.get("rbuffstat_before", ""),
                mcbsp_stop_latest.get("spcr2_before", ""),
                mcbsp_regs.get("thrsh2", ""),
                mcbsp_regs.get("thrsh1", ""),
                steelhead_hw.get("format", ""),
                steelhead_hw.get("inversion", ""),
                steelhead_hw.get("legacy_s16_only", ""),
                steelhead_hw.get("bclk", ""),
                steelhead_hw.get("bclk_override", ""),
                steelhead_hw.get("div", ""),
                steelhead_hw.get("mclk", ""),
                tas_latest.get("sdi", ""),
                tas_latest.get("sys2", ""),
                tas_latest.get("err", ""),
                tas_latest.get("mvol", ""),
                tas_pre_mute.get("sys2", ""),
                tas_pre_mute.get("err", ""),
                fmt(metric(run, "rms")),
                fmt(metric(run, "expected_tone_rms")),
                fmt(metric(run, "zero_cross_freq_hz")),
                fmt(metric(run, "zero_cross_freq_error_pct")),
                fmt(metric(run, "envelope_cv_25ms")),
                fmt(metric(run, "envelope_low_pct_25ms")),
                fmt(metric(run, "envelope_peak_to_trough_db_25ms")),
                fmt(metric(run, "envelope_mod_peak_hz_25ms")),
                fmt(metric(run, "envelope_mod_peak_score_25ms")),
                fmt(float(env_improvement), 3),
                fmt(metric(run, "harmonic_power_ratio_2_8")),
                fmt(metric(run, "clipped_pct")),
                ",".join(run.get("kernel_events", {}).get("flags", [])),
                str(analysis.get("verdict", "")),
            ]
        )

    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))

    if not rows:
        print("No probe metrics found.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", help="probe run or sweep directories")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument(
        "--baseline-json",
        default=DEFAULT_BASELINE,
        help="bad-output baseline JSON for improvement factors",
    )
    parser.add_argument("--no-baseline", action="store_true", help="skip baseline comparison")
    parser.add_argument("--max-env-cv", type=float, default=0.20)
    parser.add_argument("--max-env-low-pct", type=float, default=10.0)
    parser.add_argument("--max-env-range-db", type=float, default=6.0)
    parser.add_argument("--max-freq-error-pct", type=float, default=1.0)
    parser.add_argument("--max-harmonic-ratio", type=float, default=0.05)
    parser.add_argument("--max-clip-pct", type=float, default=1.0)
    parser.add_argument("--min-mic-rms", type=float, default=0.003)
    args = parser.parse_args()

    runs = sorted(find_runs(args.paths), key=rank_key)
    baseline = None
    if not args.no_baseline:
        baseline = read_json(args.baseline_json)

    for run in runs:
        run["analysis"] = quality_analysis(
            run,
            baseline,
            args.max_env_cv,
            args.max_env_low_pct,
            args.max_env_range_db,
            args.max_freq_error_pct,
            args.max_harmonic_ratio,
            args.max_clip_pct,
            args.min_mic_rms,
        )
    runs = sorted(runs, key=rank_key)

    if args.json:
        print(json.dumps(runs, indent=2, sort_keys=True))
    else:
        print_table(runs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
