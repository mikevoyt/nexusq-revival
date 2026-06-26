// SPDX-License-Identifier: GPL-2.0-only
/*
 * Emit raw S16_LE PCM beat pulses for Nexus Q visualizer sync calibration.
 */

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct options {
	int rate;
	int channels;
	int beats;
	int interval_ms;
	int tone_ms;
	int freq_hz;
	int amplitude;
	int leadin_ms;
};

static int parse_int(const char *s, int min, int max, int *out)
{
	char *end = NULL;
	long value;

	errno = 0;
	value = strtol(s, &end, 0);
	if (errno || !end || *end || value < min || value > max)
		return -1;
	*out = (int)value;
	return 0;
}

static void usage(const char *argv0)
{
	fprintf(stderr,
		"usage: %s [--rate N] [--channels N] [--beats N]\n"
		"          [--interval-ms N] [--tone-ms N] [--freq N]\n"
		"          [--amplitude N] [--leadin-ms N]\n"
		"\n"
		"Outputs raw S16_LE PCM beat pulses to stdout.\n",
		argv0);
}

static int parse_args(int argc, char **argv, struct options *opts)
{
	int i;

	opts->rate = 48000;
	opts->channels = 2;
	opts->beats = 12;
	opts->interval_ms = 800;
	opts->tone_ms = 70;
	opts->freq_hz = 880;
	opts->amplitude = 9000;
	opts->leadin_ms = 600;

	for (i = 1; i < argc; i++) {
		if (strcmp(argv[i], "--rate") == 0 && i + 1 < argc) {
			if (parse_int(argv[++i], 8000, 192000, &opts->rate) < 0)
				return -1;
		} else if (strcmp(argv[i], "--channels") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 1, 8, &opts->channels) < 0)
				return -1;
		} else if (strcmp(argv[i], "--beats") == 0 && i + 1 < argc) {
			if (parse_int(argv[++i], 1, 120, &opts->beats) < 0)
				return -1;
		} else if (strcmp(argv[i], "--interval-ms") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 100, 5000,
				      &opts->interval_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "--tone-ms") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 10, 1000, &opts->tone_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "--freq") == 0 && i + 1 < argc) {
			if (parse_int(argv[++i], 50, 8000, &opts->freq_hz) < 0)
				return -1;
		} else if (strcmp(argv[i], "--amplitude") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 30000,
				      &opts->amplitude) < 0)
				return -1;
		} else if (strcmp(argv[i], "--leadin-ms") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 5000,
				      &opts->leadin_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "-h") == 0 ||
			   strcmp(argv[i], "--help") == 0) {
			return 1;
		} else {
			return -1;
		}
	}

	if (opts->tone_ms >= opts->interval_ms)
		opts->tone_ms = opts->interval_ms - 1;
	return 0;
}

static int16_t triangle_sample(uint32_t phase, int amplitude)
{
	uint32_t x = phase >> 16;
	int value;

	if (x < 32768)
		value = (int)x;
	else
		value = (int)(65535U - x);

	value = (value - 16384) * 2;
	return (int16_t)(value * amplitude / 32768);
}

static int envelope(int frame, int total_frames)
{
	int attack = total_frames / 8;
	int release = total_frames / 5;
	int remaining = total_frames - frame;
	int scale = 1024;

	if (attack < 8)
		attack = 8;
	if (release < 8)
		release = 8;
	if (frame < attack)
		scale = frame * 1024 / attack;
	if (remaining < release) {
		int rel_scale = remaining * 1024 / release;

		if (rel_scale < scale)
			scale = rel_scale;
	}
	if (scale < 0)
		scale = 0;
	if (scale > 1024)
		scale = 1024;
	return scale;
}

static int write_frame(int16_t sample, int channels)
{
	uint8_t frame[16];
	int ch;

	if (channels > 8)
		return -1;
	for (ch = 0; ch < channels; ch++) {
		uint16_t raw = (uint16_t)sample;

		frame[ch * 2] = (uint8_t)(raw & 0xff);
		frame[ch * 2 + 1] = (uint8_t)(raw >> 8);
	}
	return fwrite(frame, (size_t)channels * 2, 1, stdout) == 1 ? 0 : -1;
}

static int write_silence(int frames, int channels)
{
	int i;

	for (i = 0; i < frames; i++) {
		if (write_frame(0, channels) < 0)
			return -1;
	}
	return 0;
}

int main(int argc, char **argv)
{
	struct options opts;
	uint32_t phase = 0;
	uint32_t step;
	int parse;
	int beat;
	int tone_frames;
	int interval_frames;
	int leadin_frames;

	parse = parse_args(argc, argv, &opts);
	if (parse != 0) {
		usage(argv[0]);
		return parse < 0 ? 2 : 0;
	}

	step = (uint32_t)(((uint64_t)opts.freq_hz * (uint64_t)UINT32_MAX) /
			  (uint64_t)opts.rate);
	tone_frames = opts.rate * opts.tone_ms / 1000;
	interval_frames = opts.rate * opts.interval_ms / 1000;
	leadin_frames = opts.rate * opts.leadin_ms / 1000;

	if (write_silence(leadin_frames, opts.channels) < 0)
		return 1;

	for (beat = 0; beat < opts.beats; beat++) {
		int i;

		for (i = 0; i < tone_frames; i++) {
			int sample = triangle_sample(phase, opts.amplitude);

			sample = sample * envelope(i, tone_frames) / 1024;
			if (write_frame((int16_t)sample, opts.channels) < 0)
				return 1;
			phase += step;
		}
		if (write_silence(interval_frames - tone_frames,
				  opts.channels) < 0)
			return 1;
	}

	if (write_silence(leadin_frames, opts.channels) < 0)
		return 1;

	return fflush(stdout) == 0 ? 0 : 1;
}
