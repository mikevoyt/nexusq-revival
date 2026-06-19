// SPDX-License-Identifier: GPL-2.0-only
/*
 * Nexus Q LED ring control and Squeezelite visualizer.
 *
 * Talks to the kernel-owned Steelhead AVR misc device at /dev/leds. For music
 * visualization it reads Squeezelite's VISEXPORT shared-memory sample buffer
 * and converts recent PCM energy into a low-rate RGB ring frame.
 */

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <unistd.h>

#define DEFAULT_LED_DEV "/dev/leds"
#define DEFAULT_SHM_DIR "/dev/shm"
#define DEFAULT_FPS 20
#define DEFAULT_BRIGHTNESS 255
#define DEFAULT_IDLE_BRIGHTNESS 6
#define DEFAULT_GAIN 8
#define DEFAULT_STYLE VIS_STYLE_PULSE
#define MAX_LEDS 64
#define VIS_WINDOW_SAMPLES 2048
#define VIS_EXPECTED_BUF_SIZE 16384U
#define VIS_BANDS 3

#define AVR_LED_MODE_HOST_AUTO_COMMIT 0x01

struct avr_led_rgb_vals {
	uint8_t rgb[3];
};

struct avr_led_set_range_vals {
	uint8_t start;
	uint8_t count;
	uint8_t rgb_triples;
	struct avr_led_rgb_vals rgb_vals[];
};

#define AVR_LED_MAGIC 0xe2
#define AVR_LED_GET_FIRMWARE_REVISION _IOR(AVR_LED_MAGIC, 1, uint16_t)
#define AVR_LED_GET_HARDWARE_TYPE     _IOR(AVR_LED_MAGIC, 2, uint8_t)
#define AVR_LED_GET_HARDWARE_REVISION _IOR(AVR_LED_MAGIC, 3, uint8_t)
#define AVR_LED_GET_MODE              _IOR(AVR_LED_MAGIC, 4, uint8_t)
#define AVR_LED_SET_MODE              _IOW(AVR_LED_MAGIC, 5, uint8_t)
#define AVR_LED_GET_COUNT             _IOR(AVR_LED_MAGIC, 6, uint8_t)
#define AVR_LED_SET_ALL_VALS          _IOW(AVR_LED_MAGIC, 9, \
					   struct avr_led_rgb_vals)
#define AVR_LED_SET_RANGE_VALS        _IOW(AVR_LED_MAGIC, 11, \
					   struct avr_led_set_range_vals)
#define AVR_LED_COMMIT_LED_STATE      _IOW(AVR_LED_MAGIC, 13, uint8_t)
#define AVR_LED_SET_MUTE              _IOW(AVR_LED_MAGIC, 15, \
					   struct avr_led_rgb_vals)

enum command {
	CMD_VISUALIZER,
	CMD_INFO,
	CMD_OFF,
	CMD_ALL,
	CMD_SWEEP,
};

enum visualizer_style {
	VIS_STYLE_PULSE,
	VIS_STYLE_SPECTRUM,
};

struct options {
	const char *device;
	const char *shm;
	enum command command;
	enum visualizer_style style;
	int fps;
	int brightness;
	int idle_brightness;
	int gain;
	uint8_t all_rgb[3];
};

struct vis_reader {
	int fd;
	uint8_t *map;
	size_t size;
	size_t buf_size_off;
	size_t buf_index_off;
	size_t running_off;
	size_t rate_off;
	size_t updated_off;
	size_t buffer_off;
	uint32_t buf_size;
	char path[160];
};

struct vis_levels {
	int overall;
	int bands[VIS_BANDS];
	bool running;
	uint32_t updated;
};

struct visualizer_state {
	int fluid[MAX_LEDS];
	int velocity[MAX_LEDS];
	int smooth_overall;
	int smooth_bands[VIS_BANDS];
	int limiter;
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
		"usage:\n"
		"  %s [--device /dev/leds] [--shm PATH_OR_NAME] [--fps N]\n"
		"     [--brightness 0..255] [--idle-brightness 0..255]\n"
		"     [--gain N] [--style spectrum|pulse]\n"
		"  %s --info [--device /dev/leds]\n"
		"  %s --off [--device /dev/leds]\n"
		"  %s --all R G B [--device /dev/leds]\n"
		"  %s --sweep [--device /dev/leds] [--brightness 0..255]\n",
		argv0, argv0, argv0, argv0, argv0);
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

static int parse_u8_arg(const char *s, uint8_t *out)
{
	int value;

	if (parse_int(s, 0, 255, &value) < 0)
		return -1;
	*out = (uint8_t)value;
	return 0;
}

static int clamp_int(int value, int min, int max)
{
	if (value < min)
		return min;
	if (value > max)
		return max;
	return value;
}

static int led_open(const char *device)
{
	int fd = open(device, O_RDWR | O_CLOEXEC);

	if (fd < 0)
		fprintf(stderr, "open %s failed: %s\n", device,
			strerror(errno));

	return fd;
}

static int led_get_count(int fd)
{
	uint8_t count = 0;

	if (ioctl(fd, AVR_LED_GET_COUNT, &count) < 0) {
		fprintf(stderr, "AVR_LED_GET_COUNT failed: %s\n",
			strerror(errno));
		return -1;
	}
	if (!count || count > MAX_LEDS) {
		fprintf(stderr, "unexpected LED count %u\n", count);
		return -1;
	}

	return count;
}

static int led_set_mode(int fd, uint8_t mode)
{
	if (ioctl(fd, AVR_LED_SET_MODE, &mode) < 0) {
		fprintf(stderr, "AVR_LED_SET_MODE failed: %s\n",
			strerror(errno));
		return -1;
	}

	return 0;
}

static int led_set_all(int fd, uint8_t r, uint8_t g, uint8_t b)
{
	struct avr_led_rgb_vals rgb = { .rgb = { r, g, b } };

	if (ioctl(fd, AVR_LED_SET_ALL_VALS, &rgb) < 0) {
		fprintf(stderr, "AVR_LED_SET_ALL_VALS failed: %s\n",
			strerror(errno));
		return -1;
	}

	return 0;
}

static int led_set_range(int fd, uint8_t start, uint8_t count,
			 const struct avr_led_rgb_vals *rgb)
{
	size_t size = sizeof(struct avr_led_set_range_vals) +
		      count * sizeof(*rgb);
	struct avr_led_set_range_vals *req = malloc(size);
	int ret;

	if (!req)
		return -1;

	req->start = start;
	req->count = count;
	req->rgb_triples = count;
	memcpy(req->rgb_vals, rgb, count * sizeof(*rgb));

	ret = ioctl(fd, AVR_LED_SET_RANGE_VALS, req);
	if (ret < 0)
		fprintf(stderr, "AVR_LED_SET_RANGE_VALS failed: %s\n",
			strerror(errno));
	free(req);
	return ret;
}

static void color_wheel(uint8_t pos, uint8_t *r, uint8_t *g, uint8_t *b)
{
	if (pos < 85) {
		*r = 255 - pos * 3;
		*g = pos * 3;
		*b = 0;
	} else if (pos < 170) {
		pos -= 85;
		*r = 0;
		*g = 255 - pos * 3;
		*b = pos * 3;
	} else {
		pos -= 170;
		*r = pos * 3;
		*g = 0;
		*b = 255 - pos * 3;
	}
}

static struct avr_led_rgb_vals scale_color(uint8_t hue, int brightness)
{
	struct avr_led_rgb_vals out;
	uint8_t r, g, b;

	brightness = clamp_int(brightness, 0, 255);
	color_wheel(hue, &r, &g, &b);
	out.rgb[0] = (uint8_t)((r * brightness) / 255);
	out.rgb[1] = (uint8_t)((g * brightness) / 255);
	out.rgb[2] = (uint8_t)((b * brightness) / 255);
	return out;
}

static int print_info(int fd)
{
	uint16_t fw = 0;
	uint8_t hw_type = 0;
	uint8_t hw_rev = 0;
	uint8_t mode = 0;
	uint8_t count = 0;

	if (ioctl(fd, AVR_LED_GET_FIRMWARE_REVISION, &fw) < 0 ||
	    ioctl(fd, AVR_LED_GET_HARDWARE_TYPE, &hw_type) < 0 ||
	    ioctl(fd, AVR_LED_GET_HARDWARE_REVISION, &hw_rev) < 0 ||
	    ioctl(fd, AVR_LED_GET_MODE, &mode) < 0 ||
	    ioctl(fd, AVR_LED_GET_COUNT, &count) < 0) {
		fprintf(stderr, "failed to query LED ring: %s\n",
			strerror(errno));
		return 1;
	}

	printf("firmware=%u.%u hw_type=%u hw_rev=%u led_count=%u mode=%u\n",
	       fw >> 8, fw & 0xff, hw_type, hw_rev, count, mode);
	return 0;
}

static int run_sweep(int fd, int brightness)
{
	struct avr_led_rgb_vals frame[MAX_LEDS];
	int count = led_get_count(fd);
	int i;

	if (count < 0)
		return 1;
	if (led_set_mode(fd, AVR_LED_MODE_HOST_AUTO_COMMIT) < 0)
		return 1;

	for (i = 0; i < count && keep_running; i++) {
		int j;

		memset(frame, 0, sizeof(frame));
		for (j = 0; j < count; j++) {
			int dist = abs(j - i);
			int level;

			if (dist > count / 2)
				dist = count - dist;
			level = dist == 0 ? brightness :
				dist == 1 ? brightness / 4 : 0;
			frame[j] = scale_color((uint8_t)((j * 256) / count),
					       level);
		}
		if (led_set_range(fd, 0, (uint8_t)count, frame) < 0)
			return 1;
		usleep(50000);
	}

	led_set_all(fd, 0, 0, 0);
	return 0;
}

static uint32_t read_le32(const uint8_t *p)
{
	return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
	       ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static int16_t read_le16s(const uint8_t *p)
{
	uint16_t value = (uint16_t)p[0] | ((uint16_t)p[1] << 8);

	return (int16_t)value;
}

static void vis_close(struct vis_reader *vis)
{
	if (vis->map && vis->map != MAP_FAILED)
		munmap(vis->map, vis->size);
	if (vis->fd >= 0)
		close(vis->fd);
	memset(vis, 0, sizeof(*vis));
	vis->fd = -1;
}

static int make_shm_path(const char *configured, char *path, size_t path_len)
{
	if (!configured || !configured[0])
		return -1;

	if (strncmp(configured, "/dev/", 5) == 0) {
		if (snprintf(path, path_len, "%s", configured) >=
		    (int)path_len)
			return -1;
		return 0;
	}

	if (configured[0] == '/')
		configured++;

	if (snprintf(path, path_len, "%s/%s", DEFAULT_SHM_DIR,
		     configured) >= (int)path_len)
		return -1;

	return 0;
}

static int find_squeezelite_shm(char *path, size_t path_len)
{
	DIR *dir = opendir(DEFAULT_SHM_DIR);
	struct dirent *de;

	if (!dir)
		return -1;

	while ((de = readdir(dir))) {
		if (strncmp(de->d_name, "squeezelite-", 12) != 0)
			continue;
		if (snprintf(path, path_len, "%s/%s", DEFAULT_SHM_DIR,
			     de->d_name) >= (int)path_len) {
			closedir(dir);
			return -1;
		}
		closedir(dir);
		return 0;
	}

	closedir(dir);
	return -1;
}

static int vis_detect_layout(struct vis_reader *vis)
{
	size_t off;

	for (off = 0; off + 20 < vis->size && off < 160; off += 4) {
		uint32_t buf_size = read_le32(&vis->map[off]);
		uint32_t buf_index = read_le32(&vis->map[off + 4]);
		uint32_t rate = read_le32(&vis->map[off + 12]);
		size_t sample_bytes;

		if (buf_size != VIS_EXPECTED_BUF_SIZE)
			continue;
		if (buf_index >= buf_size)
			continue;
		if (rate && (rate < 8000 || rate > 1536000))
			continue;

		sample_bytes = (size_t)buf_size * sizeof(int16_t);
		if (vis->size < sample_bytes + off + 20)
			continue;

		vis->buf_size_off = off;
		vis->buf_index_off = off + 4;
		vis->running_off = off + 8;
		vis->rate_off = off + 12;
		vis->updated_off = off + 16;
		vis->buffer_off = vis->size - sample_bytes;
		vis->buf_size = buf_size;
		return 0;
	}

	return -1;
}

static int vis_open(struct vis_reader *vis, const char *configured)
{
	struct stat st;
	char path[sizeof(vis->path)];
	int fd;

	if (configured && configured[0]) {
		if (make_shm_path(configured, path, sizeof(path)) < 0)
			return -1;
	} else if (find_squeezelite_shm(path, sizeof(path)) < 0) {
		return -1;
	}

	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	if (fstat(fd, &st) < 0 || st.st_size <= 0) {
		close(fd);
		return -1;
	}

	vis->map = mmap(NULL, (size_t)st.st_size, PROT_READ, MAP_SHARED, fd, 0);
	if (vis->map == MAP_FAILED) {
		close(fd);
		memset(vis, 0, sizeof(*vis));
		vis->fd = -1;
		return -1;
	}

	vis->fd = fd;
	vis->size = (size_t)st.st_size;
	if (snprintf(vis->path, sizeof(vis->path), "%s", path) >=
	    (int)sizeof(vis->path)) {
		vis_close(vis);
		return -1;
	}
	if (vis_detect_layout(vis) < 0) {
		vis_close(vis);
		return -1;
	}

	fprintf(stderr, "using Squeezelite visualizer shm %s\n", vis->path);
	return 0;
}

static int abs_int(int value)
{
	return value < 0 ? -value : value;
}

static int energy_to_raw_level(unsigned long mean, int gain, unsigned int scale)
{
	unsigned long long value;

	value = (unsigned long long)mean * (unsigned int)gain * scale;
	value /= 32768UL;
	return clamp_int((int)value, 0, 4096);
}

static int vis_read_levels(struct vis_reader *vis, int gain,
			   struct vis_levels *levels)
{
	uint32_t buf_size;
	uint32_t buf_index;
	uint8_t running;
	size_t samples;
	size_t start;
	size_t i;
	unsigned long long sum_total = 0;
	unsigned long long sum_low = 0;
	unsigned long long sum_mid = 0;
	unsigned long long sum_high = 0;
	int slow = 0;
	int fast = 0;
	int prev = 0;

	if (!vis->map)
		return -1;

	memset(levels, 0, sizeof(*levels));
	buf_size = read_le32(&vis->map[vis->buf_size_off]);
	buf_index = read_le32(&vis->map[vis->buf_index_off]);
	running = vis->map[vis->running_off] != 0;
	levels->updated = read_le32(&vis->map[vis->updated_off]);
	if (buf_size != vis->buf_size || buf_index >= buf_size)
		return -1;
	if (!running)
		return 0;
	levels->running = true;

	samples = buf_size < VIS_WINDOW_SAMPLES ? buf_size : VIS_WINDOW_SAMPLES;
	start = (buf_index + buf_size - samples) % buf_size;

	for (i = 0; i < samples; i++) {
		size_t idx = (start + i) % buf_size;
		int sample = read_le16s(&vis->map[vis->buffer_off +
						  idx * sizeof(int16_t)]);
		int low;
		int mid;
		int high;

		slow += (sample - slow) / 16;
		fast += (sample - fast) / 4;
		low = slow;
		mid = fast - slow;
		high = sample - fast;

		sum_total += (unsigned)abs_int(sample);
		sum_low += (unsigned)abs_int(low);
		sum_mid += (unsigned)abs_int(mid);
		sum_high += (unsigned)(abs_int(high) + abs_int(sample - prev)) / 2;
		prev = sample;
	}

	levels->overall = energy_to_raw_level(
		(unsigned long)(sum_total / samples), gain, 1024);
	levels->bands[0] = energy_to_raw_level(
		(unsigned long)(sum_low / samples), gain, 1536);
	levels->bands[1] = energy_to_raw_level(
		(unsigned long)(sum_mid / samples), gain, 4096);
	levels->bands[2] = energy_to_raw_level(
		(unsigned long)(sum_high / samples), gain, 3072);
	return 0;
}

static int smooth_level(int current, int target)
{
	if (target > current)
		return current + (target - current) / 3 + 1;
	if (target < current)
		return current - (current - target) / 8 - 1;
	return current;
}

static int update_limiter(struct visualizer_state *state,
			  const struct vis_levels *levels)
{
	int target = levels->overall;
	int i;

	for (i = 0; i < VIS_BANDS; i++) {
		if (levels->bands[i] > target)
			target = levels->bands[i];
	}

	if (state->limiter < 256)
		state->limiter = 256;

	if (target > state->limiter)
		state->limiter += (target - state->limiter) / 2 + 16;
	else
		state->limiter -= (state->limiter - target) / 96 + 1;

	if (state->limiter < 256)
		state->limiter = 256;
	return state->limiter;
}

static int normalize_level(int raw, int limiter)
{
	if (limiter < 1)
		limiter = 1;
	return clamp_int((raw * 960) / limiter, 0, 1024);
}

static void update_smoothed_levels(struct visualizer_state *state,
				   const struct vis_levels *levels)
{
	int limiter = update_limiter(state, levels);
	int i;

	state->smooth_overall = clamp_int(
		smooth_level(state->smooth_overall,
			     normalize_level(levels->overall, limiter)),
		0, 1024);
	for (i = 0; i < VIS_BANDS; i++) {
		state->smooth_bands[i] = clamp_int(
			smooth_level(state->smooth_bands[i],
				     normalize_level(levels->bands[i],
						     limiter)),
			0, 1024);
	}
}

static void add_fluid_injection(struct visualizer_state *state, int count,
				int center, int width, int amount)
{
	int d;

	width = clamp_int(width, 0, count / 3);
	amount = clamp_int(amount, 0, 1024);

	for (d = -width; d <= width; d++) {
		int dist = abs_int(d);
		int pos = (center + d + count) % count;
		int local = amount * (width + 1 - dist) / (width + 1);

		state->fluid[pos] = clamp_int(state->fluid[pos] + local,
					      0, 2048);
	}
}

static void step_fluid(struct visualizer_state *state, int count, int phase,
		       bool active)
{
	int next_fluid[MAX_LEDS];
	int next_velocity[MAX_LEDS];
	int center = phase % count;
	int width;
	int inject;
	int i;

	for (i = 0; i < count; i++) {
		int left = state->fluid[(i + count - 1) % count];
		int right = state->fluid[(i + 1) % count];
		int here = state->fluid[i];
		int velocity = state->velocity[i];
		int lap = left + right - 2 * here;
		int decay;

		velocity += lap / 8;
		velocity -= velocity / 9;
		velocity = clamp_int(velocity, -1024, 1024);

		here += velocity;
		decay = here / 28 + 1;
		here -= decay;
		if (here < 0) {
			here = 0;
			velocity = 0;
		}

		next_fluid[i] = clamp_int(here, 0, 1600);
		next_velocity[i] = velocity;
	}

	memcpy(state->fluid, next_fluid, count * sizeof(state->fluid[0]));
	memcpy(state->velocity, next_velocity,
	       count * sizeof(state->velocity[0]));

	if (!active) {
		add_fluid_injection(state, count, center, 0, 18);
		return;
	}

	width = 1 + (state->smooth_bands[0] * count) / 4096;
	inject = state->smooth_overall;
	add_fluid_injection(state, count, center, width, inject);

	add_fluid_injection(state, count, (center + count / 3) % count, 1,
			    state->smooth_bands[1] / 2);
	add_fluid_injection(state, count, (center + (2 * count) / 3) % count,
			    0, state->smooth_bands[2] / 2);
}

static void render_pulse_frame(struct avr_led_rgb_vals *frame, int count,
			       int phase, bool active,
			       const struct options *opts,
			       struct visualizer_state *state)
{
	int hue_bias = (state->smooth_bands[2] - state->smooth_bands[0]) / 8;
	int ambient = active ? state->smooth_overall / 32 : 0;
	int i;

	step_fluid(state, count, phase, active);

	for (i = 0; i < count; i++) {
		int height = clamp_int(state->fluid[i], 0, 1024);
		int brightness = opts->idle_brightness + ambient;
		uint8_t hue;

		brightness += (height * (opts->brightness -
					 opts->idle_brightness)) / 1024;
		brightness = clamp_int(brightness, 0, opts->brightness);

		hue = (uint8_t)((phase * 4 + (i * 256) / count + hue_bias) &
				0xff);
		frame[i] = scale_color(hue, brightness);
	}
}

static void render_spectrum_frame(struct avr_led_rgb_vals *frame, int count,
				  int phase, bool active,
				  const struct options *opts,
				  const struct visualizer_state *state)
{
	static const uint8_t hues[VIS_BANDS] = { 10, 85, 170 };
	int b;

	memset(frame, 0, sizeof(*frame) * count);

	if (!active) {
		frame[phase % count] = scale_color((uint8_t)(phase * 4),
						   opts->idle_brightness);
		return;
	}

	for (b = 0; b < VIS_BANDS; b++) {
		int start = (b * count) / VIS_BANDS;
		int end = ((b + 1) * count) / VIS_BANDS;
		int len = end - start;
		int lit = (state->smooth_bands[b] * len + 1023) / 1024;
		int j;

		for (j = 0; j < len; j++) {
			int pos = start + ((j + phase) % len);
			int brightness;

			if (j >= lit)
				continue;
			brightness = opts->brightness -
				(j * opts->brightness) / (lit + 1);
			frame[pos] = scale_color(hues[b], brightness);
		}
	}
}

static int run_visualizer(int fd, const struct options *opts)
{
	struct avr_led_rgb_vals frame[MAX_LEDS];
	struct vis_reader vis = { .fd = -1 };
	struct visualizer_state state = { .limiter = 512 };
	int count = led_get_count(fd);
	int interval_us;
	int phase = 0;
	int missing_ticks = 0;

	if (count < 0)
		return 1;
	if (led_set_mode(fd, AVR_LED_MODE_HOST_AUTO_COMMIT) < 0)
		return 1;

	interval_us = 1000000 / clamp_int(opts->fps, 1, 60);

	while (keep_running) {
		struct vis_levels levels;
		int ret = -1;
		bool active = false;

		memset(&levels, 0, sizeof(levels));
		if (vis.fd < 0) {
			if (vis_open(&vis, opts->shm) < 0) {
				missing_ticks++;
			} else {
				missing_ticks = 0;
			}
		}

		if (vis.fd >= 0) {
			ret = vis_read_levels(&vis, opts->gain, &levels);
			if (ret < 0) {
				vis_close(&vis);
				missing_ticks++;
			}
		}

		if (levels.running)
			active = true;
		else
			memset(&levels, 0, sizeof(levels));

		update_smoothed_levels(&state, &levels);
		if (state.smooth_overall > 12)
			active = true;
		if (missing_ticks > opts->fps * 30)
			active = false;

		switch (opts->style) {
		case VIS_STYLE_PULSE:
			render_pulse_frame(frame, count, phase, active, opts,
					   &state);
			break;
		case VIS_STYLE_SPECTRUM:
			render_spectrum_frame(frame, count, phase, active, opts,
					      &state);
			break;
		}

		if (led_set_range(fd, 0, (uint8_t)count, frame) < 0)
			break;

		phase = (phase + 1) % count;
		usleep((useconds_t)interval_us);
	}

	vis_close(&vis);
	led_set_all(fd, 0, 0, 0);
	return 0;
}

static int parse_args(int argc, char **argv, struct options *opts)
{
	int i;

	opts->device = DEFAULT_LED_DEV;
	opts->command = CMD_VISUALIZER;
	opts->style = DEFAULT_STYLE;
	opts->fps = DEFAULT_FPS;
	opts->brightness = DEFAULT_BRIGHTNESS;
	opts->idle_brightness = DEFAULT_IDLE_BRIGHTNESS;
	opts->gain = DEFAULT_GAIN;

	for (i = 1; i < argc; i++) {
		if (strcmp(argv[i], "--device") == 0 && i + 1 < argc) {
			opts->device = argv[++i];
		} else if (strcmp(argv[i], "--shm") == 0 && i + 1 < argc) {
			opts->shm = argv[++i];
		} else if (strcmp(argv[i], "--fps") == 0 && i + 1 < argc) {
			if (parse_int(argv[++i], 1, 60, &opts->fps) < 0)
				return -1;
		} else if (strcmp(argv[i], "--brightness") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 255,
				      &opts->brightness) < 0)
				return -1;
		} else if (strcmp(argv[i], "--idle-brightness") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 255,
				      &opts->idle_brightness) < 0)
				return -1;
		} else if (strcmp(argv[i], "--gain") == 0 && i + 1 < argc) {
			if (parse_int(argv[++i], 1, 64, &opts->gain) < 0)
				return -1;
		} else if (strcmp(argv[i], "--style") == 0 && i + 1 < argc) {
			const char *style = argv[++i];

			if (strcmp(style, "pulse") == 0 ||
			    strcmp(style, "fluid") == 0) {
				opts->style = VIS_STYLE_PULSE;
			} else if (strcmp(style, "spectrum") == 0) {
				opts->style = VIS_STYLE_SPECTRUM;
			} else {
				return -1;
			}
		} else if (strcmp(argv[i], "--info") == 0) {
			opts->command = CMD_INFO;
		} else if (strcmp(argv[i], "--off") == 0) {
			opts->command = CMD_OFF;
		} else if (strcmp(argv[i], "--sweep") == 0) {
			opts->command = CMD_SWEEP;
		} else if (strcmp(argv[i], "--all") == 0 && i + 3 < argc) {
			opts->command = CMD_ALL;
			if (parse_u8_arg(argv[++i], &opts->all_rgb[0]) < 0 ||
			    parse_u8_arg(argv[++i], &opts->all_rgb[1]) < 0 ||
			    parse_u8_arg(argv[++i], &opts->all_rgb[2]) < 0)
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

int main(int argc, char **argv)
{
	struct options opts;
	int parse;
	int fd;
	int ret = 0;

	parse = parse_args(argc, argv, &opts);
	if (parse != 0) {
		usage(argv[0]);
		return parse < 0 ? 2 : 0;
	}

	signal(SIGINT, handle_signal);
	signal(SIGTERM, handle_signal);
	signal(SIGHUP, SIG_IGN);

	fd = led_open(opts.device);
	if (fd < 0)
		return 1;

	switch (opts.command) {
	case CMD_INFO:
		ret = print_info(fd);
		break;
	case CMD_OFF:
		led_set_mode(fd, AVR_LED_MODE_HOST_AUTO_COMMIT);
		ret = led_set_all(fd, 0, 0, 0) < 0 ? 1 : 0;
		break;
	case CMD_ALL:
		if (led_set_mode(fd, AVR_LED_MODE_HOST_AUTO_COMMIT) < 0)
			ret = 1;
		else
			ret = led_set_all(fd, opts.all_rgb[0], opts.all_rgb[1],
					  opts.all_rgb[2]) < 0 ? 1 : 0;
		break;
	case CMD_SWEEP:
		ret = run_sweep(fd, opts.brightness);
		break;
	case CMD_VISUALIZER:
		ret = run_visualizer(fd, &opts);
		break;
	}

	close(fd);
	return ret;
}
