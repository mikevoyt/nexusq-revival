// SPDX-License-Identifier: GPL-2.0-only
/*
 * Nexus Q front-panel volume bridge.
 *
 * Reads Steelhead AVR evdev key events and adjusts a TAS5713 ALSA mixer
 * control through amixer. Keeping this policy in userspace makes the safe
 * volume range easy to tune without rebuilding the kernel.
 */

#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <signal.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef KEY_VOLUMEDOWN
#define KEY_VOLUMEDOWN 114
#endif

#ifndef KEY_VOLUMEUP
#define KEY_VOLUMEUP 115
#endif

#ifndef KEY_MUTE
#define KEY_MUTE 113
#endif

#define DEFAULT_DEVICE_NAME "Steelhead Front Panel"
#define DEFAULT_CARD "0"
#define DEFAULT_CONTROL "Master Volume"
#define DEFAULT_MIN 120
#define DEFAULT_MAX 231
#define DEFAULT_STEP 2
#define SCAN_SLEEP_SECS 1

static volatile sig_atomic_t keep_running = 1;

static void handle_signal(int sig)
{
	(void)sig;
	keep_running = 0;
}

static void log_msg(const char *fmt, ...)
{
	va_list ap;

	va_start(ap, fmt);
	vfprintf(stderr, fmt, ap);
	va_end(ap);
	fputc('\n', stderr);
	fflush(stderr);
}

static const char *env_or_default(const char *name, const char *fallback)
{
	const char *value = getenv(name);

	return value && value[0] ? value : fallback;
}

static int parse_int_env(const char *name, int fallback)
{
	const char *value = getenv(name);
	char *end = NULL;
	long parsed;

	if (!value || !value[0])
		return fallback;

	errno = 0;
	parsed = strtol(value, &end, 0);
	if (errno || !end || *end)
		return fallback;

	return (int)parsed;
}

static int clamp_int(int value, int min, int max)
{
	if (value < min)
		return min;
	if (value > max)
		return max;
	return value;
}

static int run_amixer_cset(const char *card, const char *control,
			   const char *value)
{
	char control_arg[160];
	pid_t pid;
	int status;

	if (snprintf(control_arg, sizeof(control_arg), "name=%s", control) >=
	    (int)sizeof(control_arg)) {
		log_msg("control name too long: %s", control);
		return -1;
	}

	pid = fork();
	if (pid < 0) {
		log_msg("fork failed: %s", strerror(errno));
		return -1;
	}

	if (pid == 0) {
		execlp("amixer", "amixer", "-q", "-c", card, "cset",
		       control_arg, value, (char *)NULL);
		_exit(127);
	}

	if (waitpid(pid, &status, 0) < 0) {
		log_msg("waitpid failed: %s", strerror(errno));
		return -1;
	}

	if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
		log_msg("amixer cset failed for %s=%s", control, value);
		return -1;
	}

	return 0;
}

static int read_amixer_value(const char *card, const char *control)
{
	char control_arg[160];
	char line[256];
	int pipefd[2];
	FILE *pipe_file;
	pid_t pid;
	int status;
	int found = -1;

	if (snprintf(control_arg, sizeof(control_arg), "name=%s", control) >=
	    (int)sizeof(control_arg))
		return -1;

	if (pipe(pipefd) < 0)
		return -1;

	pid = fork();
	if (pid < 0) {
		close(pipefd[0]);
		close(pipefd[1]);
		return -1;
	}

	if (pid == 0) {
		int nullfd;

		close(pipefd[0]);
		if (dup2(pipefd[1], STDOUT_FILENO) < 0)
			_exit(127);
		close(pipefd[1]);
		nullfd = open("/dev/null", O_WRONLY | O_CLOEXEC);
		if (nullfd >= 0) {
			dup2(nullfd, STDERR_FILENO);
			close(nullfd);
		}
		execlp("amixer", "amixer", "-c", card, "cget",
		       control_arg, (char *)NULL);
		_exit(127);
	}

	close(pipefd[1]);
	pipe_file = fdopen(pipefd[0], "r");
	if (!pipe_file) {
		close(pipefd[0]);
		waitpid(pid, &status, 0);
		return -1;
	}

	while (fgets(line, sizeof(line), pipe_file)) {
		char *values = strstr(line, "values=");
		char *p;

		if (!values)
			continue;
		p = line;
		while (isspace((unsigned char)*p))
			p++;
		if (*p != ':')
			continue;
		p = values + strlen("values=");
		while (*p && !isdigit((unsigned char)*p) && *p != '-')
			p++;
		if (*p) {
			found = atoi(p);
			break;
		}
	}

	fclose(pipe_file);
	if (waitpid(pid, &status, 0) < 0)
		return -1;
	if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
		return -1;

	return found;
}

static bool device_name_matches(int fd, const char *want)
{
	char name[256] = { 0 };

	if (ioctl(fd, EVIOCGNAME(sizeof(name)), name) < 0)
		return false;

	return strstr(name, want) != NULL;
}

static int open_named_input(const char *path, const char *want_name)
{
	int fd = open(path, O_RDONLY | O_CLOEXEC);

	if (fd < 0)
		return -1;

	if (!want_name || !want_name[0] || device_name_matches(fd, want_name))
		return fd;

	close(fd);
	return -1;
}

static int find_input_device(char *path, size_t path_len, const char *want_name)
{
	DIR *dir;
	struct dirent *de;

	dir = opendir("/dev/input");
	if (!dir)
		return -1;

	while ((de = readdir(dir))) {
		char candidate[128];
		int fd;

		if (strncmp(de->d_name, "event", 5) != 0)
			continue;

		if (snprintf(candidate, sizeof(candidate), "/dev/input/%s",
			     de->d_name) >= (int)sizeof(candidate))
			continue;

		fd = open_named_input(candidate, want_name);
		if (fd >= 0) {
			close(fd);
			if (snprintf(path, path_len, "%s", candidate) >=
			    (int)path_len) {
				closedir(dir);
				return -1;
			}
			closedir(dir);
			return 0;
		}
	}

	closedir(dir);
	return -1;
}

static int open_input_loop(const char *configured_path, const char *want_name)
{
	while (keep_running) {
		char discovered[128];
		const char *path = configured_path;
		int fd;

		if (!path || !path[0]) {
			if (find_input_device(discovered, sizeof(discovered),
					      want_name) < 0) {
				sleep(SCAN_SLEEP_SECS);
				continue;
			}
			path = discovered;
		}

		fd = open_named_input(path, configured_path ? NULL : want_name);
		if (fd >= 0) {
			log_msg("using input device %s", path);
			return fd;
		}

		sleep(SCAN_SLEEP_SECS);
	}

	return -1;
}

static void set_volume(const char *card, const char *control, int volume)
{
	char value[32];

	snprintf(value, sizeof(value), "%d", volume);
	if (run_amixer_cset(card, control, value) == 0)
		log_msg("%s=%d", control, volume);
}

int main(int argc, char **argv)
{
	const char *input_path = argc > 1 ? argv[1] : getenv("NQ_KNOB_INPUT");
	const char *input_name = env_or_default("NQ_KNOB_INPUT_NAME",
						DEFAULT_DEVICE_NAME);
	const char *card = env_or_default("NQ_KNOB_MIXER_CARD", DEFAULT_CARD);
	const char *control = env_or_default("NQ_KNOB_CONTROL",
					     DEFAULT_CONTROL);
	const char *mute_control = env_or_default("NQ_KNOB_MUTE_CONTROL",
						  "Speaker Switch");
	int min = parse_int_env("NQ_KNOB_MIN", DEFAULT_MIN);
	int max = parse_int_env("NQ_KNOB_MAX", DEFAULT_MAX);
	int step = parse_int_env("NQ_KNOB_STEP", DEFAULT_STEP);
	bool mute_enabled = parse_int_env("NQ_KNOB_MUTE_ENABLE", 1) != 0;
	bool muted = false;
	int volume;
	int fd;

	if (min > max) {
		int tmp = min;

		min = max;
		max = tmp;
	}
	if (step <= 0)
		step = DEFAULT_STEP;

	signal(SIGINT, handle_signal);
	signal(SIGTERM, handle_signal);
	signal(SIGHUP, SIG_IGN);
	signal(SIGCHLD, SIG_DFL);

	volume = read_amixer_value(card, control);
	if (volume < 0)
		volume = min;
	volume = clamp_int(volume, min, max);
	set_volume(card, control, volume);

	log_msg("card=%s control=%s range=%d..%d step=%d mute=%s",
		card, control, min, max, step, mute_enabled ? "on" : "off");

	fd = open_input_loop(input_path, input_name);
	if (fd < 0)
		return 1;

	while (keep_running) {
		struct input_event event;
		ssize_t n = read(fd, &event, sizeof(event));

		if (n < 0) {
			if (errno == EINTR)
				continue;
			log_msg("input read failed: %s", strerror(errno));
			close(fd);
			fd = open_input_loop(input_path, input_name);
			if (fd < 0)
				return 1;
			continue;
		}
		if (n != sizeof(event))
			continue;
		if (event.type != EV_KEY || event.value <= 0)
			continue;

		if (event.code == KEY_VOLUMEUP) {
			volume = clamp_int(volume + step, min, max);
			if (muted && mute_enabled) {
				run_amixer_cset(card, mute_control, "on");
				muted = false;
			}
			set_volume(card, control, volume);
		} else if (event.code == KEY_VOLUMEDOWN) {
			volume = clamp_int(volume - step, min, max);
			if (muted && mute_enabled) {
				run_amixer_cset(card, mute_control, "on");
				muted = false;
			}
			set_volume(card, control, volume);
		} else if (event.code == KEY_MUTE && mute_enabled) {
			muted = !muted;
			run_amixer_cset(card, mute_control, muted ? "off" : "on");
			log_msg("%s=%s", mute_control, muted ? "off" : "on");
		}
	}

	close(fd);
	return 0;
}
