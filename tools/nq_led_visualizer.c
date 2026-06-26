// SPDX-License-Identifier: GPL-2.0-only
/*
 * Nexus Q LED ring control and local audio visualizer.
 *
 * Talks to the kernel-owned Steelhead AVR misc device at /dev/leds. For music
 * visualization it reads either a local PCM level file or Squeezelite's
 * VISEXPORT shared-memory sample buffer and converts recent PCM energy into a
 * low-rate RGB ring frame.
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
#include <time.h>
#include <unistd.h>

#define DEFAULT_LED_DEV "/dev/leds"
#define DEFAULT_SHM_DIR "/dev/shm"
#define DEFAULT_FPS 60
#define DEFAULT_BRIGHTNESS 255
#define DEFAULT_IDLE_BRIGHTNESS 6
#define DEFAULT_GAIN 8
#define DEFAULT_STYLE VIS_STYLE_PULSE
#define DEFAULT_SWIRL_ENABLE 1
#define DEFAULT_SWIRL_MIN_MS 10000
#define DEFAULT_SWIRL_MAX_MS 15000
#define DEFAULT_SWIRL_DURATION_MS 2200
#define DEFAULT_SYNC_STATE_FILE "/run/nexusq-led-visualizer-state"
#define DEFAULT_SYNC_DELAY_FILE "/run/nexusq-led-sync-delay-ms"
#define LEVEL_DELAY_QUEUE 128
#define MAX_LEDS 64
#define VIS_WINDOW_SAMPLES 2048
#define VIS_EXPECTED_BUF_SIZE 16384U
#define VIS_BANDS 3
#define VIS_LEVELS (VIS_BANDS + 1)
#define VIS_OVERALL_SLOT VIS_BANDS
#define RGB_CHANNELS 3
#define LEVEL_FILE_STALE_MS 1500LL
#define TRACK_MIN_RANGE 192
#define TRACK_HISTORY 48
#define ANIM_PHASE_SCALE 1024

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
	const char *levels;
	enum command command;
	enum visualizer_style style;
	int fps;
	int brightness;
	int idle_brightness;
	int gain;
	int swirl_enable;
	int swirl_min_ms;
	int swirl_max_ms;
	int swirl_duration_ms;
	int sync_delay_ms;
	const char *sync_delay_file;
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
	long long source_updated_ms;
	int audio_delay_ms;
	long long estimated_audio_ms;
};

struct delayed_level_sample {
	struct vis_levels levels;
	long long due_ms;
};

struct level_delay_state {
	struct delayed_level_sample queue[LEVEL_DELAY_QUEUE];
	int head;
	int count;
	uint32_t last_seq;
	int last_delay_ms;
	struct vis_levels current;
	bool have_current;
};

struct visualizer_state {
	int instant_overall;
	int instant_bands[VIS_BANDS];
	int smooth_overall;
	int smooth_bands[VIS_BANDS];
	int beat_flash;
	int track_history[VIS_LEVELS][TRACK_HISTORY];
	int track_hist_pos;
	int track_hist_count;
	int track_floor[VIS_LEVELS];
	int track_peak[VIS_LEVELS];
	int palette[VIS_BANDS][RGB_CHANNELS];
	int palette_target[VIS_BANDS][RGB_CHANNELS];
	int palette_ticks;
	int texture[MAX_LEDS];
	int texture_target[MAX_LEDS];
	int texture_ticks;
	int band_phase[VIS_BANDS];
	int band_speed[VIS_BANDS];
	int band_speed_target[VIS_BANDS];
	int animation_ticks;
	int swirl_next_ticks;
	int swirl_ticks;
	int swirl_total_ticks;
	int swirl_phase;
	int swirl_speed;
	int swirl_width;
	int swirl_rgb[RGB_CHANNELS];
	uint32_t rng;
	uint32_t last_level_seq;
	uint32_t last_sync_state_seq;
	bool palette_ready;
	bool texture_ready;
	bool animation_ready;
	bool swirl_ready;
	bool frame_smooth_valid;
	struct avr_led_rgb_vals smooth_frame[MAX_LEDS];
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
		"  %s [--device /dev/leds] [--levels PATH] [--shm PATH_OR_NAME] [--fps N]\n"
		"     [--brightness 0..255] [--idle-brightness 0..255]\n"
		"     [--gain N] [--style spectrum|pulse]\n"
		"     [--swirl 0|1] [--swirl-min-ms N] [--swirl-max-ms N]\n"
		"     [--swirl-duration-ms N]\n"
		"     [--sync-delay-ms N] [--sync-delay-file PATH]\n"
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

static long long monotonic_ms(void)
{
	struct timespec ts;

	if (clock_gettime(CLOCK_MONOTONIC, &ts) < 0)
		return 0;
	return (long long)ts.tv_sec * 1000LL + ts.tv_nsec / 1000000LL;
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

static int parse_key_value_long(const char *line, const char *key, long *out)
{
	size_t key_len = strlen(key);
	char *end = NULL;
	long value;

	if (strncmp(line, key, key_len) != 0 || line[key_len] != '=')
		return -1;

	errno = 0;
	value = strtol(line + key_len + 1, &end, 0);
	if (errno || end == line + key_len + 1)
		return -1;
	*out = value;
	return 0;
}

static int parse_key_value_ll(const char *line, const char *key, long long *out)
{
	size_t key_len = strlen(key);
	char *end = NULL;
	long long value;

	if (strncmp(line, key, key_len) != 0 || line[key_len] != '=')
		return -1;
	errno = 0;
	value = strtoll(line + key_len + 1, &end, 0);
	if (errno || end == line + key_len + 1)
		return -1;
	*out = value;
	return 0;
}

static int read_int_file(const char *path, int fallback, int min, int max)
{
	char data[32];
	char *end = NULL;
	long value;
	ssize_t got;
	int fd;

	if (!path || !path[0])
		return fallback;

	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return fallback;
	got = read(fd, data, sizeof(data) - 1);
	close(fd);
	if (got <= 0)
		return fallback;
	data[got] = '\0';

	errno = 0;
	value = strtol(data, &end, 0);
	if (errno || end == data)
		return fallback;
	return clamp_int((int)value, min, max);
}

static int read_level_file(const char *path, int gain,
			   struct vis_levels *levels)
{
	char data[512];
	char *line;
	char *saveptr = NULL;
	long long updated_ms = -1;
	long long estimated_audio_ms = -1;
	long running = 0;
	long overall = 0;
	long bands[VIS_BANDS] = { 0, 0, 0 };
	long audio_delay_ms = 0;
	ssize_t got;
	int fd;
	int i;

	if (!path || !path[0])
		return -1;

	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -1;
	got = read(fd, data, sizeof(data) - 1);
	close(fd);
	if (got <= 0)
		return -1;
	data[got] = '\0';

	memset(levels, 0, sizeof(*levels));
	for (line = strtok_r(data, "\n", &saveptr); line;
	     line = strtok_r(NULL, "\n", &saveptr)) {
		long value;
		long long ll_value;

		if (parse_key_value_ll(line, "updated_ms", &ll_value) == 0) {
			updated_ms = ll_value;
		} else if (parse_key_value_long(line, "audio_delay_ms",
						&value) == 0) {
			audio_delay_ms = value;
		} else if (parse_key_value_ll(line, "estimated_audio_ms",
					      &ll_value) == 0) {
			estimated_audio_ms = ll_value;
		} else if (parse_key_value_long(line, "running", &value) == 0) {
			running = value;
		} else if (parse_key_value_long(line, "overall", &value) == 0) {
			overall = value;
		} else if (parse_key_value_long(line, "band0", &value) == 0) {
			bands[0] = value;
		} else if (parse_key_value_long(line, "band1", &value) == 0) {
			bands[1] = value;
		} else if (parse_key_value_long(line, "band2", &value) == 0) {
			bands[2] = value;
		} else if (parse_key_value_long(line, "seq", &value) == 0) {
			levels->updated = (uint32_t)value;
		}
	}

	if (updated_ms < 0)
		return -1;
	if (monotonic_ms() - updated_ms > LEVEL_FILE_STALE_MS)
		return -1;
	if (!running)
		return -1;

	levels->running = true;
	levels->source_updated_ms = updated_ms;
	levels->audio_delay_ms = (int)audio_delay_ms;
	levels->estimated_audio_ms = estimated_audio_ms >= 0 ?
				     estimated_audio_ms :
				     updated_ms + audio_delay_ms;
	levels->overall = clamp_int((int)overall * gain, 0, 4096);
	for (i = 0; i < VIS_BANDS; i++)
		levels->bands[i] = clamp_int((int)bands[i] * gain, 0, 4096);
	return 0;
}

static void level_delay_reset(struct level_delay_state *delay)
{
	memset(delay, 0, sizeof(*delay));
}

static void level_delay_push(struct level_delay_state *delay,
			     const struct vis_levels *levels, int delay_ms)
{
	struct delayed_level_sample *sample;
	int tail;

	if (!levels->updated || levels->updated == delay->last_seq)
		return;
	if (delay->count >= LEVEL_DELAY_QUEUE) {
		delay->head = (delay->head + 1) % LEVEL_DELAY_QUEUE;
		delay->count--;
	}

	tail = (delay->head + delay->count) % LEVEL_DELAY_QUEUE;
	sample = &delay->queue[tail];
	sample->levels = *levels;
	sample->due_ms = levels->estimated_audio_ms + delay_ms;
	delay->count++;
	delay->last_seq = levels->updated;
}

static int level_delay_pop_due(struct level_delay_state *delay,
			       long long now_ms, struct vis_levels *levels)
{
	bool popped = false;

	while (delay->count > 0 && delay->queue[delay->head].due_ms <= now_ms) {
		delay->current = delay->queue[delay->head].levels;
		delay->have_current = true;
		delay->head = (delay->head + 1) % LEVEL_DELAY_QUEUE;
		delay->count--;
		popped = true;
	}

	if (popped || delay->have_current) {
		*levels = delay->current;
		return 0;
	}

	memset(levels, 0, sizeof(*levels));
	return 0;
}

static int effective_sync_delay_ms(const struct options *opts)
{
	return read_int_file(opts->sync_delay_file, opts->sync_delay_ms, 0, 2000);
}

static void apply_level_sync_delay(struct level_delay_state *delay,
				   const struct options *opts,
				   struct vis_levels *levels)
{
	int delay_ms = effective_sync_delay_ms(opts);

	if (delay_ms <= 0) {
		if (delay->last_delay_ms != 0)
			level_delay_reset(delay);
		delay->last_delay_ms = 0;
		return;
	}

	if (delay->last_delay_ms != delay_ms) {
		level_delay_reset(delay);
		delay->last_delay_ms = delay_ms;
	}
	level_delay_push(delay, levels, delay_ms);
	level_delay_pop_due(delay, monotonic_ms(), levels);
}

static void write_sync_state(const struct vis_levels *levels,
			     long long commit_ms, bool active, int sync_delay_ms)
{
	char tmp[256];
	FILE *fp;
	long long target_ms;

	if (!levels->running || !levels->updated ||
	    levels->source_updated_ms <= 0)
		return;
	target_ms = levels->estimated_audio_ms + sync_delay_ms;
	if (snprintf(tmp, sizeof(tmp), "%s.tmp.%ld", DEFAULT_SYNC_STATE_FILE,
		     (long)getpid()) >= (int)sizeof(tmp))
		return;

	fp = fopen(tmp, "w");
	if (!fp)
		return;
	fprintf(fp,
		"version=1\n"
		"source=levels\n"
		"seq=%u\n"
		"commit_ms=%lld\n"
		"active=%d\n"
		"source_updated_ms=%lld\n"
		"audio_delay_ms=%d\n"
		"sync_delay_ms=%d\n"
		"estimated_audio_ms=%lld\n"
		"target_led_ms=%lld\n"
		"commit_minus_source_ms=%lld\n"
		"commit_minus_estimated_audio_ms=%lld\n"
		"commit_minus_target_ms=%lld\n"
		"overall=%d\n"
		"band0=%d\n"
		"band1=%d\n"
		"band2=%d\n",
		levels->updated, commit_ms, active ? 1 : 0,
		levels->source_updated_ms, levels->audio_delay_ms,
		sync_delay_ms, levels->estimated_audio_ms, target_ms,
		commit_ms - levels->source_updated_ms,
		commit_ms - levels->estimated_audio_ms,
		commit_ms - target_ms, levels->overall,
		levels->bands[0], levels->bands[1], levels->bands[2]);
	if (fclose(fp) == 0)
		rename(tmp, DEFAULT_SYNC_STATE_FILE);
	else
		unlink(tmp);
}

static int smooth_toward(int current, int target, int rise_div, int fall_div)
{
	int delta = target - current;
	int div;
	int step;

	if (!delta)
		return current;

	div = delta > 0 ? rise_div : fall_div;
	if (div < 1)
		div = 1;

	step = delta / div;
	if (!step)
		step = delta > 0 ? 1 : -1;
	return current + step;
}

static int smooth_level(int current, int target)
{
	if (target > current)
		return smooth_toward(current, target, 1, 4);
	if (target < current)
		return smooth_toward(current, target, 1, 9);
	return current;
}

static void push_track_history(struct visualizer_state *state,
			       const struct vis_levels *levels)
{
	int pos = state->track_hist_pos;
	int i;

	state->track_history[VIS_OVERALL_SLOT][pos] =
		clamp_int(levels->overall, 0, 4096);
	for (i = 0; i < VIS_BANDS; i++) {
		state->track_history[i][pos] =
			clamp_int(levels->bands[i], 0, 4096);
	}

	state->track_hist_pos = (state->track_hist_pos + 1) % TRACK_HISTORY;
	if (state->track_hist_count < TRACK_HISTORY)
		state->track_hist_count++;
}

static int normalize_track_slot(struct visualizer_state *state, int slot,
				int raw)
{
	int floor = 4096;
	int peak = 0;
	int range;
	int i;

	raw = clamp_int(raw, 0, 4096);
	if (state->track_hist_count <= 0)
		push_track_history(state, &(struct vis_levels) {
			.overall = raw,
			.running = true,
		});

	for (i = 0; i < state->track_hist_count; i++) {
		int value = state->track_history[slot][i];

		if (value < floor)
			floor = value;
		if (value > peak)
			peak = value;
	}

	if (floor > raw)
		floor = raw;
	if (peak < raw)
		peak = raw;

	if (peak - floor < TRACK_MIN_RANGE) {
		peak = floor + TRACK_MIN_RANGE;
		if (peak > 4096) {
			peak = 4096;
			floor = peak - TRACK_MIN_RANGE;
		}
	}

	state->track_floor[slot] = floor;
	state->track_peak[slot] = peak;

	raw -= floor;
	if (raw < 0)
		raw = 0;

	range = peak - floor;
	if (range < 1)
		range = 1;
	return clamp_int((raw * 1024) / range, 0, 1024);
}

static void reset_track_envelope(struct visualizer_state *state)
{
	memset(state->track_floor, 0, sizeof(state->track_floor));
	memset(state->track_peak, 0, sizeof(state->track_peak));
	memset(state->track_history, 0, sizeof(state->track_history));
	state->track_hist_pos = 0;
	state->track_hist_count = 0;
	state->instant_overall = 0;
	memset(state->instant_bands, 0, sizeof(state->instant_bands));
	state->smooth_overall = 0;
	memset(state->smooth_bands, 0, sizeof(state->smooth_bands));
	state->beat_flash = 0;
	state->frame_smooth_valid = false;
}

static void update_smoothed_levels(struct visualizer_state *state,
				   const struct vis_levels *levels)
{
	int previous_low = state->smooth_bands[0];
	int low_delta;
	int i;

	if (levels->updated && state->last_level_seq &&
	    levels->updated < state->last_level_seq)
		reset_track_envelope(state);
	state->last_level_seq = levels->updated;

	push_track_history(state, levels);

	state->instant_overall = normalize_track_slot(
		state, VIS_OVERALL_SLOT, levels->overall);
	state->smooth_overall = clamp_int(
		smooth_level(state->smooth_overall, state->instant_overall),
		0, 1024);
	for (i = 0; i < VIS_BANDS; i++) {
		state->instant_bands[i] = normalize_track_slot(
			state, i, levels->bands[i]);
		state->smooth_bands[i] = clamp_int(
			smooth_level(state->smooth_bands[i],
				     state->instant_bands[i]),
			0, 1024);
	}

	low_delta = state->instant_bands[0] - previous_low;
	if (low_delta > 80 && state->instant_bands[0] > 190) {
		int flash = clamp_int(low_delta * 4, 0, 1024);

		if (flash > state->beat_flash)
			state->beat_flash = flash;
	}
}

static uint8_t scaled_channel(int value, int max_brightness)
{
	value = clamp_int(value, 0, 255);
	value = (value * max_brightness) / 255;
	return (uint8_t)clamp_int(value, 0, 255);
}

static int expand_level(int value)
{
	value = clamp_int(value, 0, 1024);
	return clamp_int((value * value) / 768, 0, 1024);
}

static uint32_t visualizer_rand(struct visualizer_state *state)
{
	if (!state->rng)
		state->rng = (uint32_t)monotonic_ms() ^ (uint32_t)getpid() ^
			     0x9e3779b9U;

	state->rng ^= state->rng << 13;
	state->rng ^= state->rng >> 17;
	state->rng ^= state->rng << 5;
	return state->rng;
}

static int rand_range(struct visualizer_state *state, int min, int max)
{
	uint32_t value;

	if (max <= min)
		return min;
	value = visualizer_rand(state);
	return min + (int)(value % (uint32_t)(max - min + 1));
}

static int jittered(struct visualizer_state *state, int base, int amount)
{
	return clamp_int(base + rand_range(state, -amount, amount), 0, 255);
}

static void set_palette_color(int palette[VIS_BANDS][RGB_CHANNELS],
			      int band, int r, int g, int b)
{
	palette[band][0] = clamp_int(r, 0, 255);
	palette[band][1] = clamp_int(g, 0, 255);
	palette[band][2] = clamp_int(b, 0, 255);
}

static void choose_palette_target(struct visualizer_state *state, int fps)
{
	static const int mid_anchors[][RGB_CHANNELS] = {
		{ 70, 70, 220 },
		{ 40, 155, 215 },
		{ 150, 70, 220 },
		{ 45, 185, 120 },
		{ 200, 80, 165 },
	};
	static const int high_anchors[][RGB_CHANNELS] = {
		{ 210, 245, 255 },
		{ 245, 230, 255 },
		{ 185, 255, 230 },
		{ 255, 245, 210 },
		{ 255, 220, 235 },
	};
	int mid = rand_range(state, 0,
			     (int)(sizeof(mid_anchors) /
				   sizeof(mid_anchors[0])) - 1);
	int high = rand_range(state, 0,
			      (int)(sizeof(high_anchors) /
				    sizeof(high_anchors[0])) - 1);

	set_palette_color(state->palette_target, 0,
			  rand_range(state, 185, 255),
			  rand_range(state, 32, 140),
			  rand_range(state, 0, 70));
	set_palette_color(state->palette_target, 1,
			  jittered(state, mid_anchors[mid][0], 28),
			  jittered(state, mid_anchors[mid][1], 28),
			  jittered(state, mid_anchors[mid][2], 28));
	set_palette_color(state->palette_target, 2,
			  jittered(state, high_anchors[high][0], 18),
			  jittered(state, high_anchors[high][1], 18),
			  jittered(state, high_anchors[high][2], 18));

	state->palette_ticks = rand_range(state, fps * 5, fps * 11);
}

static void update_palette(struct visualizer_state *state, int fps)
{
	int band;
	int c;

	if (fps < 1)
		fps = DEFAULT_FPS;

	if (!state->palette_ready) {
		set_palette_color(state->palette, 0, 238, 74, 18);
		set_palette_color(state->palette, 1, 64, 115, 220);
		set_palette_color(state->palette, 2, 218, 246, 255);
		memcpy(state->palette_target, state->palette,
		       sizeof(state->palette));
		state->palette_ticks = fps * 4;
		state->palette_ready = true;
	}

	state->palette_ticks--;
	if (state->palette_ticks <= 0)
		choose_palette_target(state, fps);

	for (band = 0; band < VIS_BANDS; band++) {
		for (c = 0; c < RGB_CHANNELS; c++) {
			state->palette[band][c] = smooth_toward(
				state->palette[band][c],
				state->palette_target[band][c], 80, 80);
		}
	}
}

static int circular_weight(int pos, int center, int count, int width)
{
	int dist = abs_int(pos - center);

	if (dist > count / 2)
		dist = count - dist;
	if (dist > width)
		return 0;
	return ((width + 1 - dist) * 1024) / (width + 1);
}

static int wrap_phase(int value, int limit)
{
	if (limit <= 0)
		return 0;
	while (value < 0)
		value += limit;
	while (value >= limit)
		value -= limit;
	return value;
}

static int signed_speed(struct visualizer_state *state, int min, int max)
{
	int speed = rand_range(state, min, max);

	if (visualizer_rand(state) & 1)
		speed = -speed;
	return speed;
}

static void choose_animation_target(struct visualizer_state *state, int fps)
{
	state->band_speed_target[0] = signed_speed(state, 3, 11);
	state->band_speed_target[1] = signed_speed(state, 6, 18);
	state->band_speed_target[2] = signed_speed(state, 10, 26);
	state->animation_ticks = rand_range(state, fps * 4, fps * 10);
}

static void update_animation(struct visualizer_state *state, int count, int fps)
{
	int limit;
	int band;

	if (fps < 1)
		fps = DEFAULT_FPS;
	if (count <= 0)
		return;

	limit = count * ANIM_PHASE_SCALE;
	if (!state->animation_ready) {
		for (band = 0; band < VIS_BANDS; band++) {
			state->band_phase[band] =
				rand_range(state, 0, limit - 1);
		}
		choose_animation_target(state, fps);
		memcpy(state->band_speed, state->band_speed_target,
		       sizeof(state->band_speed));
		state->animation_ready = true;
	}

	state->animation_ticks--;
	if (state->animation_ticks <= 0)
		choose_animation_target(state, fps);

	for (band = 0; band < VIS_BANDS; band++) {
		state->band_speed[band] = smooth_toward(
			state->band_speed[band], state->band_speed_target[band],
			120, 120);
		state->band_phase[band] = wrap_phase(
			state->band_phase[band] + state->band_speed[band],
			limit);
	}
}

static int circular_weight_q10(int pos, int center_q10, int count,
			       int width_leds)
{
	int limit = count * ANIM_PHASE_SCALE;
	int pos_q10 = pos * ANIM_PHASE_SCALE;
	int width_q10 = width_leds * ANIM_PHASE_SCALE;
	int dist;

	if (count <= 0 || width_q10 <= 0)
		return 0;

	center_q10 = wrap_phase(center_q10, limit);
	dist = abs_int(pos_q10 - center_q10);
	if (dist > limit / 2)
		dist = limit - dist;
	if (dist > width_q10)
		return 0;

	return ((width_q10 + ANIM_PHASE_SCALE - dist) * 1024) /
	       (width_q10 + ANIM_PHASE_SCALE);
}

static int rotating_band_weight(const struct visualizer_state *state, int band,
				int pos, int count, int lobes,
				int width_leds)
{
	int limit = count * ANIM_PHASE_SCALE;
	int spacing;
	int best = 0;
	int lobe;

	if (count <= 0 || lobes <= 0)
		return 0;

	spacing = limit / lobes;
	for (lobe = 0; lobe < lobes; lobe++) {
		int center = state->band_phase[band] + lobe * spacing;
		int weight = circular_weight_q10(pos, center, count,
						 width_leds);

		if (weight > best)
			best = weight;
	}

	return best;
}

static int ms_to_ticks(int ms, int fps)
{
	long ticks;

	if (fps < 1)
		fps = DEFAULT_FPS;
	if (ms < 0)
		ms = 0;

	ticks = ((long)ms * fps + 999) / 1000;
	if (ticks < 1)
		ticks = 1;
	if (ticks > 60000)
		ticks = 60000;
	return (int)ticks;
}

static void schedule_next_swirl(struct visualizer_state *state,
				const struct options *opts, int fps)
{
	int min_ticks = ms_to_ticks(opts->swirl_min_ms, fps);
	int max_ticks = ms_to_ticks(opts->swirl_max_ms, fps);

	if (max_ticks < min_ticks)
		max_ticks = min_ticks;
	state->swirl_next_ticks = rand_range(state, min_ticks, max_ticks);
}

static void start_swirl(struct visualizer_state *state,
			const struct options *opts, int count, int fps)
{
	static const int swirl_colors[][RGB_CHANNELS] = {
		{ 255, 238, 190 },
		{ 68, 222, 255 },
		{ 255, 86, 168 },
		{ 134, 255, 118 },
	};
	int limit = count * ANIM_PHASE_SCALE;
	int duration = ms_to_ticks(opts->swirl_duration_ms, fps);
	int choice = rand_range(state, 0,
				(int)(sizeof(swirl_colors) /
				      sizeof(swirl_colors[0])) - 1);
	int rotations = rand_range(state, 130, 220);
	int c;

	if (limit <= 0)
		return;

	state->swirl_ticks = duration;
	state->swirl_total_ticks = duration;
	state->swirl_phase = rand_range(state, 0, limit - 1);
	state->swirl_speed = (limit * rotations) / (duration * 100);
	if (state->swirl_speed < 1)
		state->swirl_speed = 1;
	if (visualizer_rand(state) & 1)
		state->swirl_speed = -state->swirl_speed;

	state->swirl_width = count / 10;
	if (state->swirl_width < 2)
		state->swirl_width = 2;
	if (state->swirl_width > 6)
		state->swirl_width = 6;

	for (c = 0; c < RGB_CHANNELS; c++)
		state->swirl_rgb[c] =
			jittered(state, swirl_colors[choice][c], 18);
}

static void update_swirl(struct visualizer_state *state, int count, int fps,
			 bool active, const struct options *opts)
{
	int limit;

	if (!opts->swirl_enable || count <= 0) {
		state->swirl_ticks = 0;
		return;
	}
	if (!active) {
		state->swirl_ready = false;
		state->swirl_ticks = 0;
		return;
	}

	limit = count * ANIM_PHASE_SCALE;
	if (!state->swirl_ready) {
		schedule_next_swirl(state, opts, fps);
		state->swirl_ready = true;
	}

	if (state->swirl_ticks > 0) {
		state->swirl_phase = wrap_phase(
			state->swirl_phase + state->swirl_speed, limit);
		state->swirl_ticks--;
		if (state->swirl_ticks <= 0)
			schedule_next_swirl(state, opts, fps);
		return;
	}

	state->swirl_next_ticks--;
	if (state->swirl_next_ticks <= 0)
		start_swirl(state, opts, count, fps);
}

static void apply_swirl_overlay(struct avr_led_rgb_vals *frame, int count,
				const struct options *opts,
				const struct visualizer_state *state)
{
	int remaining = state->swirl_ticks;
	int total = state->swirl_total_ticks;
	int progress;
	int attack;
	int release;
	int envelope = 1024;
	int direction;
	int spacing;
	int tail_count = 8;
	int i;

	if (count <= 0 || remaining <= 0 || total <= 0)
		return;

	progress = total - remaining + 1;
	attack = total / 5;
	release = total / 3;
	if (attack < 1)
		attack = 1;
	if (release < 1)
		release = 1;
	if (progress < attack)
		envelope = (progress * 1024) / attack;
	if (remaining < release) {
		int release_env = (remaining * 1024) / release;

		if (release_env < envelope)
			envelope = release_env;
	}
	envelope = clamp_int(envelope, 0, 1024);
	if (envelope <= 0)
		return;

	direction = state->swirl_speed >= 0 ? 1 : -1;
	spacing = (count * ANIM_PHASE_SCALE) / 18;
	if (spacing < ANIM_PHASE_SCALE)
		spacing = ANIM_PHASE_SCALE;

	for (i = 0; i < count; i++) {
		int weight = 0;
		int tail;
		int c;

		for (tail = 0; tail < tail_count; tail++) {
			int fade = tail_count - tail;
			int center = state->swirl_phase -
				     direction * tail * spacing;
			int w = circular_weight_q10(i, center, count,
						    state->swirl_width +
						    tail / 3);

			weight += (w * fade * fade) /
				  (tail_count * tail_count);
		}

		weight = clamp_int(weight, 0, 1024);
		if (!weight)
			continue;

		for (c = 0; c < RGB_CHANNELS; c++) {
			int add = (state->swirl_rgb[c] * weight * envelope) /
				  (1024 * 1024);

			add = (add * opts->brightness) / 255;
			frame[i].rgb[c] = (uint8_t)clamp_int(
				frame[i].rgb[c] + add, 0, 255);
		}
	}
}

static int band_mix_channel(int level, int color, int spatial,
			    int spatial_base, int denom)
{
	int mix;

	level = clamp_int(level, 0, 1024);
	color = clamp_int(color, 0, 255);
	spatial = clamp_int(spatial, 0, 1280);
	spatial_base = clamp_int(spatial_base, 0, 1280);
	if (denom < 1)
		denom = 1;

	mix = (level * color * (spatial_base + spatial)) /
	      (1024 * denom);
	return clamp_int(mix, 0, 255);
}

static void choose_texture_target(struct visualizer_state *state, int count,
				  int fps)
{
	int blobs;
	int i;
	int b;

	if (count <= 0)
		return;

	for (i = 0; i < count; i++)
		state->texture_target[i] = rand_range(state, 760, 1120);

	blobs = rand_range(state, 2, 5);
	for (b = 0; b < blobs; b++) {
		int center = rand_range(state, 0, count - 1);
		int width = rand_range(state, 2, count / 4 > 2 ?
				       count / 4 : 2);
		int amount = rand_range(state, -220, 320);

		for (i = 0; i < count; i++) {
			int weight = circular_weight(i, center, count, width);

			state->texture_target[i] = clamp_int(
				state->texture_target[i] +
				(amount * weight) / 1024, 520, 1280);
		}
	}

	state->texture_ticks = rand_range(state, fps * 3, fps * 7);
}

static void update_texture(struct visualizer_state *state, int count, int fps)
{
	int i;

	if (fps < 1)
		fps = DEFAULT_FPS;

	if (!state->texture_ready) {
		for (i = 0; i < count; i++) {
			state->texture[i] = 1024;
			state->texture_target[i] = 1024;
		}
		state->texture_ticks = fps * 2;
		state->texture_ready = true;
	}

	state->texture_ticks--;
	if (state->texture_ticks <= 0)
		choose_texture_target(state, count, fps);

	for (i = 0; i < count; i++) {
		state->texture[i] = smooth_toward(
			state->texture[i], state->texture_target[i], 90, 90);
	}
}

static void render_pulse_frame(struct avr_led_rgb_vals *frame, int count,
			       int phase, bool active,
			       const struct options *opts,
			       struct visualizer_state *state)
{
	int base = active ? 0 : opts->idle_brightness;
	int pulse_raw;
	int body_raw;
	int sparkle_raw;
	int pulse;
	int body;
	int sparkle;
	int bass_width;
	int mid_width;
	int high_width;
	int i;

	(void)phase;
	update_palette(state, opts->fps);
	update_texture(state, count, opts->fps);
	update_animation(state, count, opts->fps);
	update_swirl(state, count, opts->fps, active, opts);

	pulse_raw = (state->instant_bands[0] * 8 +
		     state->smooth_bands[0] * 3 +
		     state->instant_overall +
		     state->beat_flash * 5) / 17;
	body_raw = (state->instant_bands[1] * 3 +
		    state->smooth_bands[1]) / 4;
	sparkle_raw = (state->instant_bands[2] * 3 +
		       state->smooth_bands[2]) / 4;

	pulse = expand_level(clamp_int((pulse_raw - 90) * 1024 / 934,
				       0, 1024));
	body = expand_level(clamp_int((body_raw - 240) * 1024 / 784,
				      0, 1024));
	sparkle = expand_level(clamp_int((sparkle_raw - 260) * 1024 / 764,
					 0, 1024));

	bass_width = count / 3;
	if (bass_width < 4)
		bass_width = 4;
	mid_width = count / 7;
	if (mid_width < 3)
		mid_width = 3;
	high_width = count / 10;
	if (high_width < 2)
		high_width = 2;

	for (i = 0; i < count; i++) {
		int bass_weight = rotating_band_weight(state, 0, i, count, 2,
						       bass_width);
		int mid_weight = rotating_band_weight(state, 1, i, count, 3,
						      mid_width);
		int high_weight = rotating_band_weight(state, 2, i, count, 5,
						       high_width);
		int scale = state->texture[i];
		int r;
		int g;
		int b;

		/* Bass stays full-ring; mids and highs add moving color bands. */
		r = base +
		    band_mix_channel(pulse, state->palette[0][0],
				     bass_weight, 980, 1024) +
		    band_mix_channel(body, state->palette[1][0],
				     mid_weight, 180, 1536) +
		    band_mix_channel(sparkle, state->palette[2][0],
				     high_weight, 80, 1024);
		g = base +
		    band_mix_channel(pulse, state->palette[0][1],
				     bass_weight, 980, 1024) +
		    band_mix_channel(body, state->palette[1][1],
				     mid_weight, 180, 1536) +
		    band_mix_channel(sparkle, state->palette[2][1],
				     high_weight, 80, 1024);
		b = base +
		    band_mix_channel(pulse, state->palette[0][2],
				     bass_weight, 980, 1024) +
		    band_mix_channel(body, state->palette[1][2],
				     mid_weight, 180, 1536) +
		    band_mix_channel(sparkle, state->palette[2][2],
				     high_weight, 80, 1024);

		frame[i].rgb[0] = scaled_channel((r * scale) / 1024,
						 opts->brightness);
		frame[i].rgb[1] = scaled_channel((g * scale) / 1024,
						 opts->brightness);
		frame[i].rgb[2] = scaled_channel((b * scale) / 1024,
						 opts->brightness);
	}

	apply_swirl_overlay(frame, count, opts, state);

	if (state->beat_flash > 0)
		state->beat_flash = clamp_int(state->beat_flash -
					      state->beat_flash / 11 - 2,
					      0, 1024);
}

static void smooth_rgb_frame(struct visualizer_state *state,
			     struct avr_led_rgb_vals *frame, int count)
{
	int i;

	if (!state->frame_smooth_valid) {
		memcpy(state->smooth_frame, frame, count * sizeof(*frame));
		state->frame_smooth_valid = true;
		return;
	}

	for (i = 0; i < count; i++) {
		int c;

		for (c = 0; c < 3; c++) {
			int current = state->smooth_frame[i].rgb[c];
			int target = frame[i].rgb[c];
			int next = smooth_toward(current, target, 1, 14);

			state->smooth_frame[i].rgb[c] = (uint8_t)next;
			frame[i].rgb[c] = (uint8_t)next;
		}
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
	struct visualizer_state state = { 0 };
	struct level_delay_state level_delay = { 0 };
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
		int sync_delay_ms = effective_sync_delay_ms(opts);
		bool active = false;

		memset(&levels, 0, sizeof(levels));
		if (read_level_file(opts->levels, opts->gain, &levels) == 0) {
			apply_level_sync_delay(&level_delay, opts, &levels);
			ret = 0;
			missing_ticks = 0;
		} else {
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

		smooth_rgb_frame(&state, frame, count);
		if (led_set_range(fd, 0, (uint8_t)count, frame) < 0)
			break;
		if (levels.running && levels.updated &&
		    levels.updated != state.last_sync_state_seq) {
			write_sync_state(&levels, monotonic_ms(), active,
					 sync_delay_ms);
			state.last_sync_state_seq = levels.updated;
		}

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
	opts->swirl_enable = DEFAULT_SWIRL_ENABLE;
	opts->swirl_min_ms = DEFAULT_SWIRL_MIN_MS;
	opts->swirl_max_ms = DEFAULT_SWIRL_MAX_MS;
	opts->swirl_duration_ms = DEFAULT_SWIRL_DURATION_MS;
	opts->sync_delay_ms = 0;
	opts->sync_delay_file = DEFAULT_SYNC_DELAY_FILE;

	for (i = 1; i < argc; i++) {
		if (strcmp(argv[i], "--device") == 0 && i + 1 < argc) {
			opts->device = argv[++i];
		} else if (strcmp(argv[i], "--levels") == 0 && i + 1 < argc) {
			opts->levels = argv[++i];
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
		} else if (strcmp(argv[i], "--swirl") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 1,
				      &opts->swirl_enable) < 0)
				return -1;
		} else if (strcmp(argv[i], "--swirl-min-ms") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 60000,
				      &opts->swirl_min_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "--swirl-max-ms") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 60000,
				      &opts->swirl_max_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "--swirl-duration-ms") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 100, 10000,
				      &opts->swirl_duration_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "--sync-delay-ms") == 0 &&
			   i + 1 < argc) {
			if (parse_int(argv[++i], 0, 2000,
				      &opts->sync_delay_ms) < 0)
				return -1;
		} else if (strcmp(argv[i], "--sync-delay-file") == 0 &&
			   i + 1 < argc) {
			opts->sync_delay_file = argv[++i];
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

	if (opts->swirl_max_ms < opts->swirl_min_ms)
		opts->swirl_max_ms = opts->swirl_min_ms;

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
