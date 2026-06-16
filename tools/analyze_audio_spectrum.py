#!/usr/bin/env python3
"""Compare tone captures for carrier stability and sideband/flutter content."""

from __future__ import annotations

import argparse
import json
import math
import struct
import wave
from pathlib import Path

import numpy as np


def read_wav(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())

    if width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    elif width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 3:
        vals = []
        for i in range(0, len(raw), 3):
            v = raw[i] | (raw[i + 1] << 8) | (raw[i + 2] << 16)
            if v & 0x800000:
                v -= 0x1000000
            vals.append(v / 8388608.0)
        data = np.asarray(vals, dtype=np.float64)
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    else:
        raise SystemExit(f"{path}: unsupported WAV sample width {width}")

    if channels > 1:
        data = data.reshape((-1, channels)).mean(axis=1)

    return rate, data


def pick_window(samples: np.ndarray, rate: int, start: float | None, duration: float | None) -> np.ndarray:
    if start is not None:
        first = max(0, int(round(start * rate)))
    else:
        frame = max(1, int(round(0.050 * rate)))
        count = max(1, len(samples) // frame)
        trimmed = samples[: count * frame].reshape((count, frame))
        levels = np.sqrt(np.mean(trimmed * trimmed, axis=1))
        peak = float(levels.max()) if len(levels) else 0.0
        active = np.flatnonzero(levels >= max(0.005, peak * 0.20))
        first = int(active[0] * frame) if len(active) else 0
        first += int(round(0.100 * rate))

    if duration is None:
        last = len(samples)
    else:
        last = first + max(1, int(round(duration * rate)))
    last = min(len(samples), last)
    if last <= first:
        raise SystemExit("selected window is empty")
    return samples[first:last]


def parabolic_peak(freqs: np.ndarray, mags: np.ndarray, idx: int) -> tuple[float, float]:
    if idx <= 0 or idx >= len(mags) - 1:
        return float(freqs[idx]), float(mags[idx])
    alpha = mags[idx - 1]
    beta = mags[idx]
    gamma = mags[idx + 1]
    denom = alpha - 2.0 * beta + gamma
    if abs(denom) < 1e-30:
        return float(freqs[idx]), float(beta)
    p = 0.5 * (alpha - gamma) / denom
    bin_hz = float(freqs[1] - freqs[0])
    return float(freqs[idx] + p * bin_hz), float(beta - 0.25 * (alpha - gamma) * p)


def spectrum(samples: np.ndarray, rate: int) -> tuple[np.ndarray, np.ndarray]:
    centered = samples - np.mean(samples)
    window = np.hanning(len(centered))
    spec = np.fft.rfft(centered * window)
    freqs = np.fft.rfftfreq(len(centered), 1.0 / rate)
    mags = np.abs(spec)
    return freqs, mags


def top_peaks(freqs: np.ndarray, mags: np.ndarray, lo: float, hi: float, limit: int = 8) -> list[dict[str, float]]:
    band = np.flatnonzero((freqs >= lo) & (freqs <= hi))
    peaks: list[tuple[float, int]] = []
    for idx in band:
        if idx == 0 or idx >= len(mags) - 1:
            continue
        if mags[idx] >= mags[idx - 1] and mags[idx] >= mags[idx + 1]:
            peaks.append((float(mags[idx]), int(idx)))
    peaks.sort(reverse=True)

    selected: list[int] = []
    min_sep_bins = max(1, int(round(2.0 / (freqs[1] - freqs[0]))))
    for _, idx in peaks:
        if all(abs(idx - other) >= min_sep_bins for other in selected):
            selected.append(idx)
            if len(selected) >= limit:
                break

    result = []
    ref = mags[selected[0]] if selected else 1.0
    for idx in selected:
        freq, mag = parabolic_peak(freqs, mags, idx)
        result.append(
            {
                "freq_hz": freq,
                "relative_db": 20.0 * math.log10(max(float(mag), 1e-30) / max(float(ref), 1e-30)),
            }
        )
    return result


def sideband_scan(
    freqs: np.ndarray,
    mags: np.ndarray,
    carrier: float,
    min_offset: float = 0.5,
    max_offset: float = 40.0,
) -> dict[str, float]:
    bin_hz = float(freqs[1] - freqs[0])
    carrier_idx = int(round(carrier / bin_hz))
    carrier_mag = float(mags[carrier_idx]) if 0 <= carrier_idx < len(mags) else 0.0
    best_offset = 0.0
    best_pair = 0.0
    best_l = 0.0
    best_u = 0.0
    for offset in np.arange(min_offset, max_offset + bin_hz / 2, bin_hz):
        li = int(round((carrier - offset) / bin_hz))
        ui = int(round((carrier + offset) / bin_hz))
        if li <= 0 or ui >= len(mags):
            continue
        lower = float(mags[li])
        upper = float(mags[ui])
        pair = math.hypot(lower, upper)
        if pair > best_pair:
            best_pair = pair
            best_offset = float(offset)
            best_l = lower
            best_u = upper
    denom = max(carrier_mag, 1e-30)
    return {
        "best_offset_hz": best_offset,
        "pair_relative_db": 20.0 * math.log10(max(best_pair, 1e-30) / denom),
        "lower_relative_db": 20.0 * math.log10(max(best_l, 1e-30) / denom),
        "upper_relative_db": 20.0 * math.log10(max(best_u, 1e-30) / denom),
    }


def envelope(samples: np.ndarray, rate: int, frame_ms: float = 25.0) -> tuple[float, np.ndarray]:
    frame = max(1, int(round(rate * frame_ms / 1000.0)))
    count = len(samples) // frame
    if count < 2:
        return 0.0, np.asarray([], dtype=np.float64)
    trimmed = samples[: count * frame].reshape((count, frame))
    levels = np.sqrt(np.mean(trimmed * trimmed, axis=1))
    return rate / frame, levels


def envelope_peak(levels: np.ndarray, env_rate: float) -> dict[str, float]:
    if len(levels) < 8 or env_rate <= 0:
        return {"envelope_peak_hz": 0.0, "envelope_peak_score": 0.0}
    centered = levels - np.mean(levels)
    if np.std(centered) <= max(np.mean(levels), 1e-30) * 0.01:
        return {"envelope_peak_hz": 0.0, "envelope_peak_score": 0.0}
    spec = np.fft.rfft(centered * np.hanning(len(centered)))
    freqs = np.fft.rfftfreq(len(centered), 1.0 / env_rate)
    power = np.abs(spec) ** 2
    band = np.flatnonzero((freqs >= 0.5) & (freqs <= 20.0))
    if len(band) == 0:
        return {"envelope_peak_hz": 0.0, "envelope_peak_score": 0.0}
    idx = int(band[np.argmax(power[band])])
    total = float(np.sum(power[band]))
    return {
        "envelope_peak_hz": float(freqs[idx]),
        "envelope_peak_score": float(power[idx] / total) if total > 0 else 0.0,
    }


def analyze(path: Path, expected: float, start: float | None, duration: float | None) -> dict[str, object]:
    rate, samples = read_wav(path)
    windowed = pick_window(samples, rate, start, duration)
    freqs, mags = spectrum(windowed, rate)
    peaks = top_peaks(freqs, mags, max(20.0, expected - 120.0), expected + 120.0)
    carrier = float(peaks[0]["freq_hz"]) if peaks else expected
    env_rate, env = envelope(windowed, rate)
    env_mean = float(np.mean(env)) if len(env) else 0.0
    env_cv = float(np.std(env) / env_mean) if env_mean > 0 else 0.0
    return {
        "path": str(path),
        "sample_rate": rate,
        "window_seconds": len(windowed) / rate,
        "rms": float(np.sqrt(np.mean(windowed * windowed))),
        "carrier_hz": carrier,
        "carrier_error_hz": carrier - expected,
        "top_peaks": peaks,
        "sidebands": sideband_scan(freqs, mags, carrier),
        "envelope_cv_25ms": env_cv,
        **envelope_peak(env, env_rate),
    }


def print_text(result: dict[str, object]) -> None:
    print(f"path={result['path']}")
    print(f"sample_rate={result['sample_rate']} window_seconds={result['window_seconds']:.3f}")
    print(f"rms={result['rms']:.6f}")
    print(
        "carrier_hz={:.3f} carrier_error_hz={:.3f}".format(
            float(result["carrier_hz"]), float(result["carrier_error_hz"])
        )
    )
    side = result["sidebands"]
    assert isinstance(side, dict)
    print(
        "sideband_offset_hz={:.3f} pair_relative_db={:.2f} lower_db={:.2f} upper_db={:.2f}".format(
            float(side["best_offset_hz"]),
            float(side["pair_relative_db"]),
            float(side["lower_relative_db"]),
            float(side["upper_relative_db"]),
        )
    )
    print(
        "envelope_cv_25ms={:.3f} envelope_peak_hz={:.3f} envelope_peak_score={:.3f}".format(
            float(result["envelope_cv_25ms"]),
            float(result["envelope_peak_hz"]),
            float(result["envelope_peak_score"]),
        )
    )
    print("top_peaks:")
    for peak in result["top_peaks"]:
        print("  {:.3f} Hz {:+.2f} dB".format(peak["freq_hz"], peak["relative_db"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected", type=float, default=500.0)
    parser.add_argument("--window-start", type=float)
    parser.add_argument("--window-duration", type=float, default=8.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("captures", nargs="+", type=Path)
    args = parser.parse_args()

    results = [
        analyze(path, args.expected, args.window_start, args.window_duration)
        for path in args.captures
    ]

    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        for idx, result in enumerate(results):
            if idx:
                print()
            print_text(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
