// SPDX-License-Identifier: GPL-2.0-only
/*
 * Process raw PCM from stdin to S16_LE stdout while publishing audio levels.
 *
 * This is intentionally small: mpg123 decodes/resamples, aplay owns ALSA, and
 * this process handles the Nexus Q's visualizer tap plus lightweight stream
 * shaping such as startup mute, in-band chimes, and sync delay.
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
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#define DEFAULT_LEVEL_FILE "/run/nexusq-audio-levels"
#define DEFAULT_UPDATE_MS 50
#define READ_BUF_SIZE 4096
#define MAX_CHIME_NOTES 4

struct options {
	const char *level_file;
	int update_ms;
	int rate;
	int channels;
	int input_format;
	int audio_delay_ms;
	int startup_mute_ms;
	int startup_fade_ms;
	const char *chime_trigger;
	int chime_ms;
	int chime_gain;
	int chime_duck_percent;
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

struct chime_note {
	unsigned int start_ms;
	unsigned int duration_ms;
	unsigned int freq_hz;
};

struct chime_state {
	bool active;
	unsigned long long frame;
	ino_t last_ino;
	off_t last_size;
	time_t last_mtime_sec;
	long last_mtime_nsec;
	uint32_t phase[MAX_CHIME_NOTES];
	uint32_t step[MAX_CHIME_NOTES];
};

struct pcm_delay {
	uint8_t *buf;
	size_t len;
	size_t pos;
	bool saw_input;
};

enum input_format {
	INPUT_FORMAT_S16_LE,
	INPUT_FORMAT_S24_LE,
	INPUT_FORMAT_S32_LE,
};

struct input_pcm {
	uint8_t carry[4];
	size_t carry_len;
};

static volatile sig_atomic_t keep_running = 1;

static const struct chime_note chime_notes[MAX_CHIME_NOTES] = {
	{ 0, 210, 523 },
	{ 90, 250, 659 },
	{ 210, 260, 880 },
	{ 360, 190, 1175 },
};

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
		"Reads raw PCM from stdin, writes S16_LE PCM to stdout, and publishes\n"
		"visualizer levels to PATH. Default PATH is %s.\n"
		"\n"
		"Optional startup gate:\n"
		"  --rate N              PCM frame rate. Default 48000.\n"
		"  --channels N          PCM channels. Default 2.\n"
		"  --input-format F      Input format: S16_LE, S24_LE, S32_LE.\n"
		"                        Output is always S16_LE. Default S16_LE.\n"
		"  --audio-delay-ms N    Delay output PCM after metering. Default 0.\n"
		"  --startup-mute-ms N   Output silence for initial decoded PCM.\n"
		"  --startup-fade-ms N   Fade in after startup mute.\n"
		"\n"
		"Optional chime injection:\n"
		"  --chime-trigger PATH  Play chime when PATH changes.\n"
		"  --chime-ms N          Chime duration. Default 550.\n"
		"  --chime-gain N        Chime gain 0-2048. Default 900.\n"
		"  --chime-duck-percent N  Music level during chime. Default 30.\n",
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

static int parse_input_format(const char *s, int *out)
{
	if (strcmp(s, "S16_LE") == 0) {
		*out = INPUT_FORMAT_S16_LE;
		return 0;
	}
	if (strcmp(s, "S24_LE") == 0) {
		*out = INPUT_FORMAT_S24_LE;
		return 0;
	}
	if (strcmp(s, "S32_LE") == 0) {
		*out = INPUT_FORMAT_S32_LE;
		return 0;
	}
	return -1;
}

static int parse_args(int argc, char **argv, struct options *opts)
{
	int i;

	opts->level_file = DEFAULT_LEVEL_FILE;
	opts->update_ms = DEFAULT_UPDATE_MS;
	opts->rate = 48000;
	opts->channels = 2;
	opts->input_format = INPUT_FORMAT_S16_LE;
	opts->audio_delay_ms = 0;
	opts->startup_mute_ms = 0;
	opts->startup_fade_ms = 0;
	opts->chime_trigger = NULL;
	opts->chime_ms = 550;
	opts->chime_gain = 900;
	opts->chime_duck_percent = 30;

	for (i = 1; i < argc; i++) {
		if (strcmp(argv[i], "--levels") == 0 && i + 1 < argc) {
			opts->level_file = argv[++i];
		} else if (strcmp(argv[i], "--update-ms") == 0 && i + 1 < argc) {
			if (parse_int(argv[++i], 10, 1000, &opts->update_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "--rate") == 0 && i + 1 < argc) {
			if (parse_int(argv[++i], 8000, 192000, &opts->rate) < 0)
				return -1;
		} else if (strcmp(argv[i], "--channels") == 0 && i + 1 < argc) {
			if (parse_int(argv[++i], 1, 8, &opts->channels) < 0)
				return -1;
		} else if (strcmp(argv[i], "--input-format") == 0 &&
			   i + 1 < argc) {
			if (parse_input_format(argv[++i], &opts->input_format) < 0)
				return -1;
		} else if (strcmp(argv[i], "--audio-delay-ms") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 2000,
				      &opts->audio_delay_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "--startup-mute-ms") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 10000,
				      &opts->startup_mute_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "--startup-fade-ms") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 10000,
				      &opts->startup_fade_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "--chime-trigger") == 0 &&
			   i + 1 < argc) {
			opts->chime_trigger = argv[++i];
		} else if (strcmp(argv[i], "--chime-ms") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 100, 5000,
				      &opts->chime_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "--chime-gain") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 2048,
				      &opts->chime_gain) < 0)
				return -1;
		} else if (strcmp(argv[i], "--chime-duck-percent") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 100,
				      &opts->chime_duck_percent) < 0)
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

static long stat_mtime_nsec(const struct stat *st)
{
#if defined(__APPLE__) && !defined(_POSIX_C_SOURCE)
	return st->st_mtimespec.tv_nsec;
#elif defined(__linux__)
	return st->st_mtim.tv_nsec;
#else
	(void)st;
	return 0;
#endif
}

static int16_t read_le16s(const uint8_t *p)
{
	uint16_t value = (uint16_t)p[0] | ((uint16_t)p[1] << 8);

	return (int16_t)value;
}

static void write_le16s(uint8_t *p, int16_t value)
{
	uint16_t raw = (uint16_t)value;

	p[0] = (uint8_t)(raw & 0xff);
	p[1] = (uint8_t)(raw >> 8);
}

static int32_t sign_extend_24(uint32_t value)
{
	if (value & 0x00800000U)
		value |= 0xff000000U;
	return (int32_t)value;
}

static size_t input_sample_bytes(int format)
{
	switch (format) {
	case INPUT_FORMAT_S16_LE:
		return 2;
	case INPUT_FORMAT_S24_LE:
	case INPUT_FORMAT_S32_LE:
		return 4;
	default:
		return 2;
	}
}

static int16_t read_input_sample_s16(int format, const uint8_t *p)
{
	switch (format) {
	case INPUT_FORMAT_S16_LE:
		return read_le16s(p);
	case INPUT_FORMAT_S24_LE: {
		uint32_t raw = (uint32_t)p[0] |
			       ((uint32_t)p[1] << 8) |
			       ((uint32_t)p[2] << 16);
		return (int16_t)(sign_extend_24(raw) >> 8);
	}
	case INPUT_FORMAT_S32_LE: {
		uint32_t raw = (uint32_t)p[0] |
			       ((uint32_t)p[1] << 8) |
			       ((uint32_t)p[2] << 16) |
			       ((uint32_t)p[3] << 24);
		return (int16_t)((int32_t)raw >> 16);
	}
	default:
		return read_le16s(p);
	}
}

static size_t convert_input_to_s16(const struct options *opts,
				   struct input_pcm *input, const uint8_t *in,
				   size_t in_len, uint8_t *out,
				   size_t out_cap)
{
	size_t sample_bytes = input_sample_bytes(opts->input_format);
	size_t in_pos = 0;
	size_t out_len = 0;

	if (sample_bytes == 2 && input->carry_len == 0) {
		size_t even_len = in_len - (in_len % 2);

		if (even_len > out_cap)
			even_len = out_cap - (out_cap % 2);
		memcpy(out, in, even_len);
		out_len = even_len;
		if (even_len < in_len) {
			input->carry[0] = in[even_len];
			input->carry_len = 1;
		}
		return out_len;
	}

	if (input->carry_len) {
		while (input->carry_len < sample_bytes && in_pos < in_len)
			input->carry[input->carry_len++] = in[in_pos++];
		if (input->carry_len == sample_bytes && out_len + 2 <= out_cap) {
			write_le16s(&out[out_len], read_input_sample_s16(
						    opts->input_format,
						    input->carry));
			out_len += 2;
			input->carry_len = 0;
		}
	}

	while (in_pos + sample_bytes <= in_len && out_len + 2 <= out_cap) {
		write_le16s(&out[out_len],
			    read_input_sample_s16(opts->input_format,
						  &in[in_pos]));
		out_len += 2;
		in_pos += sample_bytes;
	}

	input->carry_len = 0;
	while (in_pos < in_len && input->carry_len < sizeof(input->carry))
		input->carry[input->carry_len++] = in[in_pos++];

	return out_len;
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
			 bool running, int audio_delay_ms)
{
	char dir[256];
	char tmp[320];
	FILE *fp;
	long long updated_ms = monotonic_ms();
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
		"audio_delay_ms=%d\n"
		"estimated_audio_ms=%lld\n"
		"running=%d\n"
		"overall=%d\n"
		"band0=%d\n"
		"band1=%d\n"
		"band2=%d\n",
		state->seq, updated_ms, audio_delay_ms,
		updated_ms + (long long)audio_delay_ms, running ? 1 : 0,
		overall, low, mid, high);
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

static int trigger_changed(struct chime_state *chime, const struct stat *st)
{
	long nsec = stat_mtime_nsec(st);

	return st->st_ino != chime->last_ino ||
	       st->st_size != chime->last_size ||
	       st->st_mtime != chime->last_mtime_sec ||
	       nsec != chime->last_mtime_nsec;
}

static void remember_trigger(struct chime_state *chime, const struct stat *st)
{
	chime->last_ino = st->st_ino;
	chime->last_size = st->st_size;
	chime->last_mtime_sec = st->st_mtime;
	chime->last_mtime_nsec = stat_mtime_nsec(st);
}

static void init_chime(struct chime_state *chime, const struct options *opts)
{
	struct stat st;
	int i;

	memset(chime, 0, sizeof(*chime));
	for (i = 0; i < MAX_CHIME_NOTES; i++) {
		chime->step[i] = (uint32_t)(((uint64_t)chime_notes[i].freq_hz *
					     (uint64_t)UINT32_MAX) /
					    (uint64_t)opts->rate);
	}

	if (opts->chime_trigger && opts->chime_trigger[0] &&
	    stat(opts->chime_trigger, &st) == 0)
		remember_trigger(chime, &st);
}

static void maybe_start_chime(struct chime_state *chime,
			      const struct options *opts)
{
	struct stat st;
	int i;

	if (!opts->chime_trigger || !opts->chime_trigger[0])
		return;
	if (stat(opts->chime_trigger, &st) < 0)
		return;
	if (!trigger_changed(chime, &st))
		return;

	remember_trigger(chime, &st);
	chime->active = true;
	chime->frame = 0;
	for (i = 0; i < MAX_CHIME_NOTES; i++)
		chime->phase[i] = 0;
}

static int wave_from_phase(uint32_t phase)
{
	uint32_t x = phase >> 16;
	int value;

	if (x < 32768)
		value = (int)x;
	else
		value = (int)(65535U - x);

	return (value - 16384) * 2;
}

static int envelope_scale(unsigned int pos_ms, unsigned int duration_ms)
{
	unsigned int remaining = duration_ms > pos_ms ? duration_ms - pos_ms : 0;
	unsigned int attack = 18;
	unsigned int release = 85;
	unsigned int scale = 1024;

	if (pos_ms < attack)
		scale = pos_ms * 1024 / attack;
	if (remaining < release) {
		unsigned int rel_scale = remaining * 1024 / release;

		if (rel_scale < scale)
			scale = rel_scale;
	}
	if (scale > 1024)
		scale = 1024;
	return (int)scale;
}

static int synth_chime_sample(struct chime_state *chime,
			      const struct options *opts)
{
	unsigned int now_ms;
	int mixed = 0;
	int i;

	if (!chime->active)
		return 0;

	now_ms = (unsigned int)(chime->frame * 1000ULL /
			       (unsigned long long)opts->rate);
	if (now_ms >= (unsigned int)opts->chime_ms) {
		chime->active = false;
		return 0;
	}

	for (i = 0; i < MAX_CHIME_NOTES; i++) {
		const struct chime_note *note = &chime_notes[i];
		unsigned int pos_ms;
		int env;
		int wave;

		if (now_ms < note->start_ms ||
		    now_ms >= note->start_ms + note->duration_ms)
			continue;

		pos_ms = now_ms - note->start_ms;
		env = envelope_scale(pos_ms, note->duration_ms);
		chime->phase[i] += chime->step[i];
		wave = wave_from_phase(chime->phase[i]);
		mixed += wave * env / 1024;
	}

	return clamp_int(mixed * opts->chime_gain / 2048, -22000, 22000);
}

static void apply_chime(struct chime_state *chime, const struct options *opts,
			uint8_t *buf, size_t len)
{
	size_t frame_bytes = (size_t)opts->channels * 2;
	size_t off;

	if (!opts->chime_trigger || !opts->chime_trigger[0])
		return;

	maybe_start_chime(chime, opts);
	if (!chime->active)
		return;

	for (off = 0; off + frame_bytes <= len; off += frame_bytes) {
		int chime_sample = synth_chime_sample(chime, opts);
		int ch;

		for (ch = 0; ch < opts->channels; ch++) {
			uint8_t *p = &buf[off + (size_t)ch * 2];
			int sample = read_le16s(p);

			sample = sample * opts->chime_duck_percent / 100;
			sample = clamp_int(sample + chime_sample, -32768, 32767);
			write_le16s(p, (int16_t)sample);
		}
		chime->frame++;
		if (!chime->active)
			break;
	}
}

static void apply_startup_gate(const struct options *opts, uint8_t *buf,
			       size_t len, unsigned long long *sample_pos)
{
	unsigned long long mute_frames;
	unsigned long long fade_frames;
	size_t i;

	if (opts->startup_mute_ms <= 0 && opts->startup_fade_ms <= 0)
		return;

	mute_frames = (unsigned long long)opts->rate *
		      (unsigned long long)opts->startup_mute_ms / 1000ULL;
	fade_frames = (unsigned long long)opts->rate *
		      (unsigned long long)opts->startup_fade_ms / 1000ULL;

	for (i = 0; i + 1 < len; i += 2) {
		unsigned long long frame = *sample_pos /
					   (unsigned long long)opts->channels;
		int sample = read_le16s(&buf[i]);
		int gated = sample;

		if (frame < mute_frames) {
			gated = 0;
		} else if (fade_frames > 0 &&
			   frame < mute_frames + fade_frames) {
			unsigned long long fade_pos = frame - mute_frames;

			gated = (int)((long long)sample * (long long)fade_pos /
				      (long long)fade_frames);
		}

		write_le16s(&buf[i], (int16_t)gated);
		(*sample_pos)++;
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

static int init_pcm_delay(struct pcm_delay *delay, const struct options *opts)
{
	size_t frame_bytes;
	unsigned long long delay_bytes;

	memset(delay, 0, sizeof(*delay));
	if (opts->audio_delay_ms <= 0)
		return 0;

	frame_bytes = (size_t)opts->channels * 2;
	delay_bytes = (unsigned long long)opts->rate *
		      (unsigned long long)frame_bytes *
		      (unsigned long long)opts->audio_delay_ms / 1000ULL;
	if (delay_bytes < frame_bytes)
		delay_bytes = frame_bytes;
	delay_bytes -= delay_bytes % frame_bytes;
	if (delay_bytes > (unsigned long long)SIZE_MAX)
		return -1;

	delay->buf = calloc(1, (size_t)delay_bytes);
	if (!delay->buf)
		return -1;
	delay->len = (size_t)delay_bytes;
	return 0;
}

static void free_pcm_delay(struct pcm_delay *delay)
{
	free(delay->buf);
	memset(delay, 0, sizeof(*delay));
}

static void apply_pcm_delay(struct pcm_delay *delay, uint8_t *buf, size_t len)
{
	size_t i;

	if (!delay->buf || !delay->len)
		return;

	for (i = 0; i < len; i++) {
		uint8_t delayed = delay->buf[delay->pos];

		delay->buf[delay->pos] = buf[i];
		buf[i] = delayed;
		delay->pos++;
		if (delay->pos >= delay->len)
			delay->pos = 0;
	}
	if (len)
		delay->saw_input = true;
}

static int flush_pcm_delay(struct pcm_delay *delay)
{
	uint8_t zeros[READ_BUF_SIZE];
	size_t remaining;

	if (!delay->buf || !delay->len || !delay->saw_input)
		return 0;

	remaining = delay->len;
	memset(zeros, 0, sizeof(zeros));
	while (remaining && keep_running) {
		size_t chunk = remaining < sizeof(zeros) ? remaining :
							   sizeof(zeros);

		apply_pcm_delay(delay, zeros, chunk);
		if (write_all(STDOUT_FILENO, zeros, chunk) < 0)
			return -1;
		memset(zeros, 0, chunk);
		remaining -= chunk;
	}
	return 0;
}

int main(int argc, char **argv)
{
	struct options opts;
	struct meter_state state = { 0 };
	struct chime_state chime;
	struct pcm_delay delay;
	struct input_pcm input = { 0 };
	uint8_t inbuf[READ_BUF_SIZE];
	uint8_t buf[READ_BUF_SIZE + 8];
	int parse;
	int ret = 0;
	unsigned long long output_sample_pos = 0;

	parse = parse_args(argc, argv, &opts);
	if (parse != 0) {
		usage(argv[0]);
		return parse < 0 ? 2 : 0;
	}

	signal(SIGINT, handle_signal);
	signal(SIGTERM, handle_signal);
	signal(SIGHUP, handle_signal);
	signal(SIGPIPE, handle_signal);

	init_chime(&chime, &opts);
	if (init_pcm_delay(&delay, &opts) < 0) {
		fprintf(stderr, "nq-pcm-level-tap: failed to allocate audio delay\n");
		return 1;
	}
	state.last_write_ms = monotonic_ms();
	write_levels(opts.level_file, &state, true, opts.audio_delay_ms);

	while (keep_running) {
		ssize_t got = read(STDIN_FILENO, inbuf, sizeof(inbuf));
		size_t pcm_len;
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

		pcm_len = convert_input_to_s16(&opts, &input, inbuf, (size_t)got,
					       buf, sizeof(buf));
		if (pcm_len == 0)
			continue;

		meter_pcm(&state, buf, pcm_len);
		apply_startup_gate(&opts, buf, pcm_len, &output_sample_pos);
		apply_chime(&chime, &opts, buf, pcm_len);
		apply_pcm_delay(&delay, buf, pcm_len);
		now = monotonic_ms();
		if (now - state.last_write_ms >= opts.update_ms)
			publish = true;

		if (write_all(STDOUT_FILENO, buf, pcm_len) < 0) {
			ret = 1;
			break;
		}

		if (publish) {
			state.seq++;
			write_levels(opts.level_file, &state, true,
				     opts.audio_delay_ms);
			reset_sums(&state);
			state.last_write_ms = now;
		}
	}

	if (ret == 0 && flush_pcm_delay(&delay) < 0)
		ret = 1;
	state.seq++;
	reset_sums(&state);
	write_levels(opts.level_file, &state, false, opts.audio_delay_ms);
	free_pcm_delay(&delay);
	return ret;
}
