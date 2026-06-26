// SPDX-License-Identifier: GPL-2.0-only
/*
 * Pass raw S16_LE PCM from stdin to stdout while publishing coarse audio levels.
 *
 * This is intentionally small: mpg123 decodes/resamples, aplay owns ALSA, and
 * this process only observes the PCM stream for the Nexus Q LED visualizer.
 */

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define DEFAULT_LEVEL_FILE "/run/nexusq-audio-levels"
#define DEFAULT_UPDATE_MS 50
#define READ_BUF_SIZE 4096

struct options {
	const char *level_file;
	int update_ms;
};

struct meter_state {
	unsigned long long sum_total;
	unsigned long long sum_low;
	unsigned long long sum_mid;
	unsigned long long sum_high;
	unsigned long samples;
	int slow;
	int fast;
	int prev;
	unsigned long seq;
	long long last_write_ms;
};

static volatile sig_atomic_t keep_running = 1;

static void handle_signal(int sig)
{
	(void)sig;
	keep_running = 0;
}

static void usage(const char *argv0)
{
	fprintf(stderr,
		"usage: %s [--levels PATH] [--update-ms N]\n"
		"\n"
		"Reads S16_LE PCM from stdin, writes it unchanged to stdout, and\n"
		"publishes visualizer levels to PATH. Default PATH is %s.\n",
		argv0, DEFAULT_LEVEL_FILE);
}

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

static int parse_args(int argc, char **argv, struct options *opts)
{
	int i;

	opts->level_file = DEFAULT_LEVEL_FILE;
	opts->update_ms = DEFAULT_UPDATE_MS;

	for (i = 1; i < argc; i++) {
		if (strcmp(argv[i], "--levels") == 0 && i + 1 < argc) {
			opts->level_file = argv[++i];
		} else if (strcmp(argv[i], "--update-ms") == 0 && i + 1 < argc) {
			if (parse_int(argv[++i], 10, 1000, &opts->update_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "-h") == 0 ||
			   strcmp(argv[i], "--help") == 0) {
			return 1;
		} else {
			return -1;
		}
	}

	return 0;
}

static long long monotonic_ms(void)
{
	struct timespec ts;

	if (clock_gettime(CLOCK_MONOTONIC, &ts) < 0)
		return 0;
	return (long long)ts.tv_sec * 1000LL + ts.tv_nsec / 1000000LL;
}

static int abs_int(int value)
{
	return value < 0 ? -value : value;
}

static int clamp_int(int value, int min, int max)
{
	if (value < min)
		return min;
	if (value > max)
		return max;
	return value;
}

static int16_t read_le16s(const uint8_t *p)
{
	uint16_t value = (uint16_t)p[0] | ((uint16_t)p[1] << 8);

	return (int16_t)value;
}

static int level_from_mean(unsigned long mean, unsigned int scale)
{
	unsigned long long value = (unsigned long long)mean * scale;

	value /= 32768UL;
	return clamp_int((int)value, 0, 4096);
}

static void dirname_for_path(const char *path, char *dir, size_t dir_len)
{
	const char *slash = strrchr(path, '/');
	size_t len;

	if (!slash) {
		snprintf(dir, dir_len, ".");
		return;
	}
	len = (size_t)(slash - path);
	if (len == 0)
		len = 1;
	if (len >= dir_len)
		len = dir_len - 1;
	memcpy(dir, path, len);
	dir[len] = '\0';
}

static void mkdir_p_one(const char *path)
{
	char tmp[256];
	char *p;

	if (!path || !path[0])
		return;
	if (snprintf(tmp, sizeof(tmp), "%s", path) >= (int)sizeof(tmp))
		return;

	for (p = tmp + 1; *p; p++) {
		if (*p != '/')
			continue;
		*p = '\0';
		mkdir(tmp, 0755);
		*p = '/';
	}
	mkdir(tmp, 0755);
}

static void write_levels(const char *path, const struct meter_state *state,
			 bool running)
{
	char dir[256];
	char tmp[320];
	FILE *fp;
	unsigned long samples = state->samples ? state->samples : 1;
	int overall = 0;
	int low = 0;
	int mid = 0;
	int high = 0;

	if (!path || !path[0])
		return;

	if (running && state->samples) {
		overall = level_from_mean(
			(unsigned long)(state->sum_total / samples), 1024);
		low = level_from_mean(
			(unsigned long)(state->sum_low / samples), 1536);
		mid = level_from_mean(
			(unsigned long)(state->sum_mid / samples), 4096);
		high = level_from_mean(
			(unsigned long)(state->sum_high / samples), 3072);
	}

	dirname_for_path(path, dir, sizeof(dir));
	mkdir_p_one(dir);
	if (snprintf(tmp, sizeof(tmp), "%s.tmp.%ld", path, (long)getpid()) >=
	    (int)sizeof(tmp))
		return;

	fp = fopen(tmp, "w");
	if (!fp)
		return;
	fprintf(fp,
		"version=1\n"
		"source=pcm\n"
		"seq=%lu\n"
		"updated_ms=%lld\n"
		"running=%d\n"
		"overall=%d\n"
		"band0=%d\n"
		"band1=%d\n"
		"band2=%d\n",
		state->seq, monotonic_ms(), running ? 1 : 0, overall, low,
		mid, high);
	if (fclose(fp) == 0)
		rename(tmp, path);
	else
		unlink(tmp);
}

static void reset_sums(struct meter_state *state)
{
	state->sum_total = 0;
	state->sum_low = 0;
	state->sum_mid = 0;
	state->sum_high = 0;
	state->samples = 0;
}

static void meter_pcm(struct meter_state *state, const uint8_t *buf, size_t len)
{
	size_t i;

	for (i = 0; i + 1 < len; i += 2) {
		int sample = read_le16s(&buf[i]);
		int low;
		int mid;
		int high;

		state->slow += (sample - state->slow) / 16;
		state->fast += (sample - state->fast) / 4;
		low = state->slow;
		mid = state->fast - state->slow;
		high = sample - state->fast;

		state->sum_total += (unsigned)abs_int(sample);
		state->sum_low += (unsigned)abs_int(low);
		state->sum_mid += (unsigned)abs_int(mid);
		state->sum_high += (unsigned)(abs_int(high) +
					      abs_int(sample - state->prev)) / 2;
		state->prev = sample;
		state->samples++;
	}
}

static ssize_t write_all(int fd, const uint8_t *buf, size_t len)
{
	size_t off = 0;

	while (off < len) {
		ssize_t written = write(fd, buf + off, len - off);

		if (written < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		if (written == 0)
			return -1;
		off += (size_t)written;
	}
	return (ssize_t)off;
}

int main(int argc, char **argv)
{
	struct options opts;
	struct meter_state state = { 0 };
	uint8_t buf[READ_BUF_SIZE];
	int parse;
	int ret = 0;

	parse = parse_args(argc, argv, &opts);
	if (parse != 0) {
		usage(argv[0]);
		return parse < 0 ? 2 : 0;
	}

	signal(SIGINT, handle_signal);
	signal(SIGTERM, handle_signal);
	signal(SIGHUP, handle_signal);
	signal(SIGPIPE, handle_signal);

	state.last_write_ms = monotonic_ms();
	write_levels(opts.level_file, &state, true);

	while (keep_running) {
		ssize_t got = read(STDIN_FILENO, buf, sizeof(buf));
		long long now;
		bool publish = false;

		if (got < 0) {
			if (errno == EINTR)
				continue;
			ret = 1;
			break;
		}
		if (got == 0)
			break;

		meter_pcm(&state, buf, (size_t)got);
		now = monotonic_ms();
		if (now - state.last_write_ms >= opts.update_ms)
			publish = true;

		if (write_all(STDOUT_FILENO, buf, (size_t)got) < 0) {
			ret = 1;
			break;
		}

		if (publish) {
			state.seq++;
			write_levels(opts.level_file, &state, true);
			reset_sums(&state);
			state.last_write_ms = now;
		}
	}

	state.seq++;
	reset_sums(&state);
	write_levels(opts.level_file, &state, false);
	return ret;
}
