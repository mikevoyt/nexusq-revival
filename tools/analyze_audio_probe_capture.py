#!/usr/bin/env python3
"""Analyze a Nexus Q audio probe microphone capture.

The metrics are intentionally simple and dependency-free. They are meant to
turn a "sounds fluttery/distorted" report into comparable numbers across
kernel images, not to replace listening.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave


def decode_to_wav(path: str) -> tuple[str, tempfile.TemporaryDirectory[str] | None]:
    if path.lower().endswith(".wav"):
        return path, None

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required to decode non-WAV captures")

    tmpdir = tempfile.TemporaryDirectory(prefix="nq-audio-")
    out = os.path.join(tmpdir.name, "capture.wav")
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-y",
            "-i",
            path,
            "-ac",
            "1",
            "-ar",
            "48000",
            "-sample_fmt",
            "s16",
            out,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    return out, tmpdir


def read_wav_mono(path: str, wav_channel: str = "mix") -> tuple[int, list[float]]:
    with wave.open(path, "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())

    if width == 1:
        vals = [(b - 128) / 128.0 for b in raw]
    elif width == 2:
        count = len(raw) // 2
        vals = [v / 32768.0 for v in struct.unpack("<" + "h" * count, raw)]
    elif width == 3:
        vals = []
        for i in range(0, len(raw), 3):
            v = raw[i] | (raw[i + 1] << 8) | (raw[i + 2] << 16)
            if v & 0x800000:
                v -= 0x1000000
            vals.append(v / 8388608.0)
    elif width == 4:
        count = len(raw) // 4
        vals = [v / 2147483648.0 for v in struct.unpack("<" + "i" * count, raw)]
    else:
        raise SystemExit(f"unsupported WAV sample width: {width}")

    if channels > 1 and wav_channel != "mix":
        if wav_channel == "left":
            channel_index = 0
        elif wav_channel == "right":
            channel_index = 1
        else:
            raise SystemExit(f"unsupported WAV channel: {wav_channel}")
        if channel_index >= channels:
            raise SystemExit(
                f"WAV has {channels} channel(s), cannot read {wav_channel}"
            )
        vals = vals[channel_index::channels]
    elif channels > 1:
        mono = []
        for i in range(0, len(vals), channels):
            frame = vals[i : i + channels]
            mono.append(sum(frame) / len(frame))
        vals = mono

    return rate, vals


def rms(samples: list[float]) -> float:
    if not samples:
        return 0.0
    return math.sqrt(sum(x * x for x in samples) / len(samples))


def active_region(samples: list[float], rate: int) -> tuple[int, int, list[float]]:
    if not samples:
        return 0, 0, []

    win = max(1, int(rate * 0.050))
    levels = []
    for start in range(0, len(samples), win):
        levels.append(rms(samples[start : start + win]))

    peak_level = max(levels) if levels else 0.0
    threshold = max(0.005, peak_level * 0.20)
    active = [i for i, level in enumerate(levels) if level >= threshold]
    if not active:
        return 0, len(samples), samples

    start = max(0, active[0] * win)
    end = min(len(samples), (active[-1] + 1) * win)
    guard = int(rate * 0.100)
    if end - start > 2 * guard:
        start += guard
        end -= guard
    return start, end, samples[start:end]


def zero_cross_frequency(samples: list[float], rate: int) -> float:
    crossings = 0
    last = 0
    for sample in samples:
        sign = 1 if sample > 0 else -1 if sample < 0 else last
        if last and sign and sign != last:
            crossings += 1
        if sign:
            last = sign
    duration = len(samples) / rate if rate else 0.0
    return crossings / (2.0 * duration) if duration else 0.0


def goertzel_power(samples: list[float], rate: int, freq: float) -> float:
    if not samples or rate <= 0:
        return 0.0
    omega = 2.0 * math.pi * freq / rate
    coeff = 2.0 * math.cos(omega)
    prev = 0.0
    prev2 = 0.0
    for sample in samples:
        value = sample + coeff * prev - prev2
        prev2 = prev
        prev = value
    return max(0.0, prev2 * prev2 + prev * prev - coeff * prev * prev2)


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(100.0, pct)) / 100.0 * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def envelope_modulation_metrics(levels: list[float], env_rate: float) -> dict[str, float]:
    if len(levels) < 8 or env_rate <= 0:
        return {
            "envelope_mod_peak_hz_25ms": 0.0,
            "envelope_mod_peak_score_25ms": 0.0,
        }

    mean = sum(levels) / len(levels)
    if mean <= 0:
        return {
            "envelope_mod_peak_hz_25ms": 0.0,
            "envelope_mod_peak_score_25ms": 0.0,
        }

    centered_rms = math.sqrt(sum((level - mean) ** 2 for level in levels) / len(levels))
    if centered_rms / mean < 0.01:
        return {
            "envelope_mod_peak_hz_25ms": 0.0,
            "envelope_mod_peak_score_25ms": 0.0,
        }

    n = len(levels)
    windowed = []
    for i, level in enumerate(levels):
        hann = 0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1)) if n > 1 else 1.0
        windowed.append((level - mean) * hann)

    min_bin = max(1, int(math.ceil(0.5 * n / env_rate)))
    max_bin = min(n // 2, int(math.floor(15.0 * n / env_rate)))
    if max_bin < min_bin:
        return {
            "envelope_mod_peak_hz_25ms": 0.0,
            "envelope_mod_peak_score_25ms": 0.0,
        }

    best_bin = 0
    best_power = 0.0
    total_power = 0.0
    for k in range(min_bin, max_bin + 1):
        real = 0.0
        imag = 0.0
        for i, value in enumerate(windowed):
            angle = 2.0 * math.pi * k * i / n
            real += value * math.cos(angle)
            imag -= value * math.sin(angle)
        power = real * real + imag * imag
        total_power += power
        if power > best_power:
            best_power = power
            best_bin = k

    return {
        "envelope_mod_peak_hz_25ms": best_bin * env_rate / n if best_bin else 0.0,
        "envelope_mod_peak_score_25ms": best_power / total_power if total_power > 0 else 0.0,
    }


def envelope_metrics(samples: list[float], rate: int) -> dict[str, float]:
    win = max(1, int(rate * 0.025))
    raw_levels = [rms(samples[i : i + win]) for i in range(0, len(samples), win)]
    levels = [x for x in raw_levels if x > 0.001]
    if len(levels) < 2:
        return {
            "envelope_cv_25ms": 0.0,
            "envelope_low_pct_25ms": 0.0,
            "envelope_p05_25ms": 0.0,
            "envelope_p50_25ms": 0.0,
            "envelope_p95_25ms": 0.0,
            "envelope_peak_to_trough_db_25ms": 0.0,
            "envelope_mod_peak_hz_25ms": 0.0,
            "envelope_mod_peak_score_25ms": 0.0,
        }

    mean = sum(levels) / len(levels)
    if mean <= 0:
        cv = 0.0
    else:
        var = sum((x - mean) ** 2 for x in levels) / len(levels)
        cv = math.sqrt(var) / mean

    p05 = percentile(levels, 5.0)
    p50 = percentile(levels, 50.0)
    p95 = percentile(levels, 95.0)
    low_threshold = p50 * 0.5
    low_count = sum(1 for level in levels if level < low_threshold)
    low_pct = 100.0 * low_count / len(levels)
    peak_to_trough_db = 0.0
    if p05 > 0 and p95 > 0:
        peak_to_trough_db = 20.0 * math.log10(p95 / p05)

    metrics = {
        "envelope_cv_25ms": cv,
        "envelope_low_pct_25ms": low_pct,
        "envelope_p05_25ms": p05,
        "envelope_p50_25ms": p50,
        "envelope_p95_25ms": p95,
        "envelope_peak_to_trough_db_25ms": peak_to_trough_db,
    }
    metrics.update(envelope_modulation_metrics(raw_levels, rate / win))
    return metrics


def analyze_samples(
    samples: list[float],
    rate: int,
    expected: float,
    *,
    window_start_s: float | None = None,
    window_duration_s: float | None = None,
    use_active_region: bool = True,
) -> dict[str, float | int]:
    base_start = 0
    windowed = samples
    if rate > 0 and (window_start_s is not None or window_duration_s is not None):
        base_start = max(0, int((window_start_s or 0.0) * rate))
        if window_duration_s is None:
            base_end = len(samples)
        else:
            base_end = base_start + max(0, int(window_duration_s * rate))
        windowed = samples[base_start : min(len(samples), base_end)]

    if use_active_region:
        start, end, active = active_region(windowed, rate)
        if not active:
            active = windowed
    else:
        start = 0
        end = len(windowed)
        active = windowed

    peak = max((abs(x) for x in active), default=0.0)
    signal_rms = rms(active)
    fundamental = goertzel_power(active, rate, expected)
    tone_rms = 0.0
    if active and fundamental > 0:
        # Goertzel power for a bin-centered sine is (N * peak / 2)^2.
        tone_rms = math.sqrt(2.0 * fundamental) / len(active)
    harmonics = [goertzel_power(active, rate, expected * n) for n in range(2, 9)]
    odd_harmonics = [goertzel_power(active, rate, expected * n) for n in (3, 5, 7)]
    harmonic_ratio = sum(harmonics) / fundamental if fundamental > 0 else 0.0
    odd_ratio = sum(odd_harmonics) / fundamental if fundamental > 0 else 0.0
    clipped = sum(1 for x in active if abs(x) >= 0.98)
    zc_freq = zero_cross_frequency(active, rate)
    env = envelope_metrics(active, rate)
    rms_dbfs = 20.0 * math.log10(signal_rms) if signal_rms > 0 else -120.0
    peak_dbfs = 20.0 * math.log10(peak) if peak > 0 else -120.0
    tone_to_rms_db = (
        20.0 * math.log10(tone_rms / signal_rms)
        if tone_rms > 0 and signal_rms > 0
        else -120.0
    )

    metrics: dict[str, float | int] = {
        "sample_rate_hz": rate,
        "input_samples": len(samples),
        "active_start_s": (base_start + start) / rate if rate else 0.0,
        "active_end_s": (base_start + end) / rate if rate else 0.0,
        "active_duration_s": len(active) / rate if rate else 0.0,
        "rms": signal_rms,
        "rms_dbfs": rms_dbfs,
        "peak": peak,
        "peak_dbfs": peak_dbfs,
        "crest_factor": peak / signal_rms if signal_rms > 0 else 0.0,
        "clipped_pct": 100.0 * clipped / len(active) if active else 0.0,
        "zero_cross_freq_hz": zc_freq,
        "zero_cross_freq_error_pct": 100.0 * (zc_freq - expected) / expected if expected else 0.0,
        "expected_freq_hz": expected,
        "expected_tone_rms": tone_rms,
        "expected_tone_to_rms_db": tone_to_rms_db,
        "harmonic_power_ratio_2_8": harmonic_ratio,
        "odd_harmonic_power_ratio_3_5_7": odd_ratio,
    }
    metrics.update(env)
    return metrics


def self_test(expected: float) -> dict[str, dict[str, float | int]]:
    rate = 48000
    duration = 3.0
    frames = int(rate * duration)
    sine = [0.2 * math.sin(2.0 * math.pi * expected * n / rate) for n in range(frames)]
    square = [0.2 if math.sin(2.0 * math.pi * expected * n / rate) >= 0 else -0.2 for n in range(frames)]
    flutter = [
        (0.2 * (0.55 + 0.45 * math.sin(2.0 * math.pi * 9.0 * n / rate)))
        * math.sin(2.0 * math.pi * expected * n / rate)
        for n in range(frames)
    ]
    return {
        "sine": analyze_samples(sine, rate, expected),
        "square": analyze_samples(square, rate, expected),
        "flutter": analyze_samples(flutter, rate, expected),
    }


def print_text(metrics: dict[str, float | int]) -> None:
    for key in sorted(metrics):
        value = metrics[key]
        if isinstance(value, float):
            print(f"{key}: {value:.6g}")
        else:
            print(f"{key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("capture", nargs="?", help="WAV/M4A/etc microphone capture")
    parser.add_argument("--expected", type=float, default=440.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--window-start",
        type=float,
        help="analyze from this capture offset in seconds",
    )
    parser.add_argument(
        "--window-duration",
        type=float,
        help="analyze at most this many seconds after --window-start",
    )
    parser.add_argument(
        "--no-active-region",
        action="store_true",
        help="analyze the full capture/window instead of auto-detecting activity",
    )
    parser.add_argument(
        "--wav-channel",
        choices=("mix", "left", "right"),
        default="mix",
        help="channel to analyze for WAV input; non-WAV captures are decoded as mono",
    )
    args = parser.parse_args()

    if args.self_test:
        result = self_test(args.expected)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if not args.capture:
        parser.error("capture path is required unless --self-test is used")

    wav_path, tmpdir = decode_to_wav(args.capture)
    try:
        rate, samples = read_wav_mono(wav_path, args.wav_channel)
        metrics = analyze_samples(
            samples,
            rate,
            args.expected,
            window_start_s=args.window_start,
            window_duration_s=args.window_duration,
            use_active_region=not args.no_active_region,
        )
    finally:
        if tmpdir is not None:
            tmpdir.cleanup()

    if args.json:
        print(json.dumps(metrics, indent=2, sort_keys=True))
    else:
        print_text(metrics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
