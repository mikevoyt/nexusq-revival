// SPDX-License-Identifier: GPL-2.0-only
/*
 * Nexus Q LED ring control and Squeezelite visualizer.
 *
 * Talks to the kernel-owned Steelhead AVR misc device at /dev/leds. For music
 * visualization it reads Squeezelite's VISEXPORT shared-memory sample buffer
 * and converts recent PCM amplitude into a rotating low-rate RGB ring frame.
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
#define MAX_LEDS 64
#define VIS_WINDOW_SAMPLES 2048
#define VIS_EXPECTED_BUF_SIZE 16384U

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

struct options {
	const char *device;
	const char *shm;
	enum command command;
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
	size_t buffer_off;
	uint32_t buf_size;
	char path[160];
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
		"     [--gain N]\n"
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

	for (off = 0; off + 16 < vis->size && off < 160; off += 4) {
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
		if (vis->size < sample_bytes + off + 16)
			continue;

		vis->buf_size_off = off;
		vis->buf_index_off = off + 4;
		vis->running_off = off + 8;
		vis->rate_off = off + 12;
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

static int vis_read_level(struct vis_reader *vis, int gain)
{
	uint32_t buf_size;
	uint32_t buf_index;
	uint8_t running;
	size_t samples;
	size_t start;
	size_t i;
	unsigned long long sum = 0;
	unsigned long mean;
	int level;

	if (!vis->map)
		return -1;

	buf_size = read_le32(&vis->map[vis->buf_size_off]);
	buf_index = read_le32(&vis->map[vis->buf_index_off]);
	running = vis->map[vis->running_off] != 0;
	if (buf_size != vis->buf_size || buf_index >= buf_size)
		return -1;
	if (!running)
		return 0;

	samples = buf_size < VIS_WINDOW_SAMPLES ? buf_size : VIS_WINDOW_SAMPLES;
	start = (buf_index + buf_size - samples) % buf_size;

	for (i = 0; i < samples; i++) {
		size_t idx = (start + i) % buf_size;
		int sample = read_le16s(&vis->map[vis->buffer_off +
						  idx * sizeof(int16_t)]);

		if (sample < 0)
			sample = -sample;
		sum += (unsigned)sample;
	}

	mean = (unsigned long)(sum / samples);
	level = (int)((mean * (unsigned long)gain * 1024UL) / 32768UL);
	return clamp_int(level, 0, 1024);
}

static void render_frame(struct avr_led_rgb_vals *frame, int count, int phase,
			 int level, bool active, const struct options *opts)
{
	int lit = (level * count + 1023) / 1024;
	int ambient = active ? (level * opts->idle_brightness) / 1024 : 0;
	int span;
	int i;

	if (active && lit < 1)
		lit = 1;
	span = lit / 2 + 1;

	for (i = 0; i < count; i++) {
		int dist = abs(i - phase);
		int brightness = ambient;
		uint8_t hue;

		if (dist > count / 2)
			dist = count - dist;

		if (active && dist < span) {
			int local = opts->brightness -
				    (dist * opts->brightness) / span;

			if (local > brightness)
				brightness = local;
		} else if (!active && dist == 0) {
			brightness = opts->idle_brightness;
		}

		hue = (uint8_t)((phase * 7 + (i * 256) / count) & 0xff);
		frame[i] = scale_color(hue, brightness);
	}
}

static int run_visualizer(int fd, const struct options *opts)
{
	struct avr_led_rgb_vals frame[MAX_LEDS];
	struct vis_reader vis = { .fd = -1 };
	int count = led_get_count(fd);
	int interval_us;
	int phase = 0;
	int smooth = 0;
	int missing_ticks = 0;

	if (count < 0)
		return 1;
	if (led_set_mode(fd, AVR_LED_MODE_HOST_AUTO_COMMIT) < 0)
		return 1;

	interval_us = 1000000 / clamp_int(opts->fps, 1, 60);

	while (keep_running) {
		int level = -1;
		bool active = false;

		if (vis.fd < 0) {
			if (vis_open(&vis, opts->shm) < 0) {
				missing_ticks++;
			} else {
				missing_ticks = 0;
			}
		}

		if (vis.fd >= 0) {
			level = vis_read_level(&vis, opts->gain);
			if (level < 0) {
				vis_close(&vis);
				missing_ticks++;
			}
		}

		if (level > 0) {
			active = true;
			if (level > smooth)
				smooth += (level - smooth) / 3 + 1;
			else
				smooth -= (smooth - level) / 8 + 1;
		} else {
			smooth -= smooth / 12 + 1;
		}
		smooth = clamp_int(smooth, 0, 1024);

		if (smooth > 8)
			active = true;
		if (missing_ticks > opts->fps * 30)
			active = false;

		render_frame(frame, count, phase, smooth, active, opts);
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
