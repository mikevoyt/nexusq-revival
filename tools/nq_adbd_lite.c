// SPDX-License-Identifier: GPL-2.0-only
/*
 * Minimal Nexus Q ADB daemon.
 *
 * This implements enough of the ADB device-side TCP transport for bring-up:
 * unauthenticated CNXN/OPEN/OKAY/WRTE/CLSE, shell:<cmd> services backed by a
 * local pseudo-terminal, sync: file transfer, and simple reboot services. It
 * is intentionally not a replacement for Android adbd; it is a small debug
 * bridge for the Debian appliance image.
 */

#define _GNU_SOURCE

#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
#include <utime.h>

#ifndef ADB_PORT
#define ADB_PORT 5555
#endif

#define A_SYNC 0x434e5953U
#define A_CNXN 0x4e584e43U
#define A_OPEN 0x4e45504fU
#define A_OKAY 0x59414b4fU
#define A_CLSE 0x45534c43U
#define A_WRTE 0x45545257U

#define A_VERSION 0x01000000U
#define A_MAXDATA 4096U
#define SHELL_LOCAL_ID 1U

#define ID4(a, b, c, d) \
	((uint32_t)(a) | ((uint32_t)(b) << 8) | \
	 ((uint32_t)(c) << 16) | ((uint32_t)(d) << 24))

#define S_ID_STAT ID4('S', 'T', 'A', 'T')
#define S_ID_LIST ID4('L', 'I', 'S', 'T')
#define S_ID_SEND ID4('S', 'E', 'N', 'D')
#define S_ID_RECV ID4('R', 'E', 'C', 'V')
#define S_ID_DENT ID4('D', 'E', 'N', 'T')
#define S_ID_DONE ID4('D', 'O', 'N', 'E')
#define S_ID_DATA ID4('D', 'A', 'T', 'A')
#define S_ID_OKAY ID4('O', 'K', 'A', 'Y')
#define S_ID_FAIL ID4('F', 'A', 'I', 'L')
#define S_ID_QUIT ID4('Q', 'U', 'I', 'T')

#define SYNC_DATA_MAX (A_MAXDATA - 8U)

struct adb_msg {
	uint32_t command;
	uint32_t arg0;
	uint32_t arg1;
	uint32_t data_length;
	uint32_t data_check;
	uint32_t magic;
};

struct adb_stream {
	int fd;
	uint32_t local_id;
	uint32_t remote_id;
	unsigned char in[A_MAXDATA + 1];
	size_t in_pos;
	size_t in_len;
	bool closed;
};

static volatile sig_atomic_t keep_running = 1;

static void on_signal(int sig)
{
	(void)sig;
	keep_running = 0;
}

static uint32_t adb_checksum(const unsigned char *data, size_t len)
{
	uint32_t sum = 0;

	while (len--)
		sum += *data++;

	return sum;
}

static ssize_t read_full(int fd, void *buf, size_t len)
{
	char *p = buf;
	size_t done = 0;

	while (done < len) {
		ssize_t n = read(fd, p + done, len - done);

		if (n == 0)
			return 0;
		if (n < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		done += (size_t)n;
	}

	return (ssize_t)done;
}

static int write_full(int fd, const void *buf, size_t len)
{
	const char *p = buf;
	size_t done = 0;

	while (done < len) {
		ssize_t n = write(fd, p + done, len - done);

		if (n < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		done += (size_t)n;
	}

	return 0;
}

static int adb_send(int fd, uint32_t command, uint32_t arg0, uint32_t arg1,
		    const void *data, size_t len)
{
	struct adb_msg msg;

	if (len > A_MAXDATA)
		return -1;

	memset(&msg, 0, sizeof(msg));
	msg.command = command;
	msg.arg0 = arg0;
	msg.arg1 = arg1;
	msg.data_length = (uint32_t)len;
	msg.data_check = data ? adb_checksum(data, len) : 0;
	msg.magic = command ^ 0xffffffffU;

	if (write_full(fd, &msg, sizeof(msg)) < 0)
		return -1;
	if (len && write_full(fd, data, len) < 0)
		return -1;

	return 0;
}

static int adb_recv(int fd, struct adb_msg *msg, unsigned char *data,
		    size_t data_cap)
{
	ssize_t n;

	n = read_full(fd, msg, sizeof(*msg));
	if (n <= 0)
		return (int)n;
	if (msg->magic != (msg->command ^ 0xffffffffU))
		return -1;
	if (msg->data_length > data_cap)
		return -1;
	if (msg->data_length) {
		n = read_full(fd, data, msg->data_length);
		if (n <= 0)
			return (int)n;
		if (adb_checksum(data, msg->data_length) != msg->data_check)
			return -1;
	}
	data[msg->data_length] = '\0';

	return 1;
}

static int stream_wait_okay(struct adb_stream *stream)
{
	unsigned char data[A_MAXDATA + 1];

	while (keep_running && !stream->closed) {
		struct adb_msg msg;
		int ret = adb_recv(stream->fd, &msg, data, sizeof(data) - 1);

		if (ret <= 0)
			return -1;
		if (msg.command == A_OKAY)
			return 0;
		if (msg.command == A_WRTE) {
			if (msg.arg1 != stream->local_id) {
				adb_send(stream->fd, A_CLSE, stream->local_id,
					 msg.arg0, NULL, 0);
				continue;
			}
			adb_send(stream->fd, A_OKAY, stream->local_id,
				 stream->remote_id, NULL, 0);
			if (stream->in_pos != stream->in_len)
				return -1;
			memcpy(stream->in, data, msg.data_length);
			stream->in_pos = 0;
			stream->in_len = msg.data_length;
			continue;
		}
		if (msg.command == A_CLSE) {
			stream->closed = true;
			return -1;
		}
	}

	return -1;
}

static int stream_send(struct adb_stream *stream, const void *data, size_t len)
{
	const unsigned char *p = data;

	while (len > 0 && !stream->closed) {
		size_t chunk = len > A_MAXDATA ? A_MAXDATA : len;

		if (adb_send(stream->fd, A_WRTE, stream->local_id,
			     stream->remote_id, p, chunk) < 0)
			return -1;
		if (stream_wait_okay(stream) < 0)
			return -1;
		p += chunk;
		len -= chunk;
	}

	return stream->closed ? -1 : 0;
}

static int stream_fill(struct adb_stream *stream)
{
	while (keep_running && !stream->closed) {
		struct adb_msg msg;
		int ret = adb_recv(stream->fd, &msg, stream->in,
				   sizeof(stream->in) - 1);

		if (ret <= 0)
			return -1;

		switch (msg.command) {
		case A_WRTE:
			if (msg.arg1 != stream->local_id) {
				adb_send(stream->fd, A_CLSE, stream->local_id,
					 msg.arg0, NULL, 0);
				continue;
			}
			adb_send(stream->fd, A_OKAY, stream->local_id,
				 stream->remote_id, NULL, 0);
			stream->in_pos = 0;
			stream->in_len = msg.data_length;
			return 0;
		case A_CLSE:
			stream->closed = true;
			return -1;
		case A_OKAY:
			break;
		default:
			break;
		}
	}

	return -1;
}

static int stream_read_exact(struct adb_stream *stream, void *buf, size_t len)
{
	unsigned char *out = buf;

	while (len > 0) {
		size_t avail;
		size_t take;

		if (stream->in_pos == stream->in_len &&
		    stream_fill(stream) < 0)
			return -1;

		avail = stream->in_len - stream->in_pos;
		take = avail < len ? avail : len;
		memcpy(out, stream->in + stream->in_pos, take);
		stream->in_pos += take;
		out += take;
		len -= take;
	}

	return 0;
}

static void stream_close(struct adb_stream *stream)
{
	if (!stream->closed) {
		adb_send(stream->fd, A_CLSE, stream->local_id,
			 stream->remote_id, NULL, 0);
		stream->closed = true;
	}
}

static int set_cloexec(int fd)
{
	int flags = fcntl(fd, F_GETFD);

	if (flags < 0)
		return -1;
	return fcntl(fd, F_SETFD, flags | FD_CLOEXEC);
}

static int open_pty(char *slave_name, size_t slave_name_len)
{
	int master;
	char *name;

	master = posix_openpt(O_RDWR | O_NOCTTY);
	if (master < 0)
		return -1;
	if (grantpt(master) < 0 || unlockpt(master) < 0) {
		close(master);
		return -1;
	}

	name = ptsname(master);
	if (!name) {
		close(master);
		return -1;
	}
	snprintf(slave_name, slave_name_len, "%s", name);
	set_cloexec(master);

	return master;
}

static const char *shell_basename(const char *shell)
{
	const char *slash = strrchr(shell, '/');

	return slash ? slash + 1 : shell;
}

static const char *choose_shell(void)
{
	const char *configured = getenv("NQ_ADBD_SHELL");

	if (configured && configured[0] && access(configured, X_OK) == 0)
		return configured;
	if (access("/bin/bash", X_OK) == 0)
		return "/bin/bash";
	return "/bin/sh";
}

static pid_t spawn_shell(int *pty_fd, const char *command)
{
	char slave_name[128];
	int master;
	int slave;
	pid_t pid;
	bool interactive = !command || !command[0];
	const char *shell = choose_shell();
	const char *shell_name = shell_basename(shell);
	bool is_bash = strcmp(shell_name, "bash") == 0;

	master = open_pty(slave_name, sizeof(slave_name));
	if (master < 0)
		return -1;

	pid = fork();
	if (pid < 0) {
		close(master);
		return -1;
	}

	if (pid == 0) {
		signal(SIGINT, SIG_DFL);
		signal(SIGTERM, SIG_DFL);
		signal(SIGCHLD, SIG_DFL);
		setenv("TERM", "xterm-256color", 0);
		setenv("HOME", "/root", 0);
		setenv("SHELL", shell, 1);
		setsid();

		slave = open(slave_name, O_RDWR | O_NOCTTY);
		if (slave < 0)
			_exit(127);
		ioctl(slave, TIOCSCTTY, 0);
		dup2(slave, STDIN_FILENO);
		dup2(slave, STDOUT_FILENO);
		dup2(slave, STDERR_FILENO);
		if (slave > STDERR_FILENO)
			close(slave);
		close(master);

		if (interactive) {
			execl(shell, shell_name, "-i", (char *)NULL);
		} else if (is_bash) {
			execl(shell, shell_name, "-lc", command, (char *)NULL);
		} else {
			execl(shell, shell_name, "-c", command, (char *)NULL);
		}
		_exit(127);
	}

	*pty_fd = master;
	return pid;
}

static const char *shell_command_from_service(const char *service)
{
	const char *p;

	if (strncmp(service, "shell:", 6) == 0)
		return service + 6;

	/*
	 * Some modern clients request shell protocol variants. We do not
	 * advertise shell_v2, but accepting the prefix makes diagnostics easier
	 * if a host still tries it.
	 */
	if (strncmp(service, "shell", 5) != 0)
		return NULL;
	p = strchr(service, ':');
	if (!p)
		return "";
	return p + 1;
}

static void reap_child(pid_t pid)
{
	int status;

	if (pid > 0)
		while (waitpid(pid, &status, WNOHANG) > 0)
			;
}

static uint32_t clamp_u32_off(off_t value)
{
	if (value < 0)
		return 0;
	if ((uint64_t)value > UINT32_MAX)
		return UINT32_MAX;
	return (uint32_t)value;
}

static uint32_t clamp_u32_time(time_t value)
{
	if (value < 0)
		return 0;
	if ((uint64_t)value > UINT32_MAX)
		return UINT32_MAX;
	return (uint32_t)value;
}

static int sync_send_status(struct adb_stream *stream, uint32_t id,
			    const char *msg)
{
	unsigned char out[A_MAXDATA];
	uint32_t len = msg ? (uint32_t)strlen(msg) : 0;

	if (8U + len > sizeof(out))
		len = sizeof(out) - 8U;
	memcpy(out, &id, 4);
	memcpy(out + 4, &len, 4);
	if (len)
		memcpy(out + 8, msg, len);

	return stream_send(stream, out, 8U + len);
}

static int sync_send_okay(struct adb_stream *stream)
{
	return sync_send_status(stream, S_ID_OKAY, "");
}

static int sync_send_fail(struct adb_stream *stream, const char *msg)
{
	return sync_send_status(stream, S_ID_FAIL, msg ? msg : "failed");
}

static int sync_read_path(struct adb_stream *stream, uint32_t len, char **out)
{
	char *path;

	if (len == 0 || len > PATH_MAX * 2U)
		return -1;

	path = calloc(1, (size_t)len + 1U);
	if (!path)
		return -1;
	if (stream_read_exact(stream, path, len) < 0) {
		free(path);
		return -1;
	}
	path[len] = '\0';
	*out = path;
	return 0;
}

static int mkdir_one_if_missing(const char *path, mode_t mode)
{
	struct stat st;

	if (mkdir(path, mode) == 0)
		return 0;
	if (errno != EEXIST)
		return -1;
	if (stat(path, &st) == 0 && S_ISDIR(st.st_mode))
		return 0;
	errno = ENOTDIR;
	return -1;
}

static int mkdir_p_parent(const char *path)
{
	char tmp[PATH_MAX * 2];
	char *p;

	if (!path || !path[0])
		return -1;
	if (snprintf(tmp, sizeof(tmp), "%s", path) >= (int)sizeof(tmp)) {
		errno = ENAMETOOLONG;
		return -1;
	}

	p = strrchr(tmp, '/');
	if (!p)
		return 0;
	if (p == tmp)
		return 0;
	*p = '\0';

	for (p = tmp + (tmp[0] == '/'); *p; p++) {
		if (*p != '/')
			continue;
		*p = '\0';
		if (tmp[0] && mkdir_one_if_missing(tmp, 0755) < 0)
			return -1;
		*p = '/';
	}

	return mkdir_one_if_missing(tmp, 0755);
}

static int mkdir_p_path(const char *path, mode_t mode)
{
	if (mkdir_p_parent(path) < 0)
		return -1;
	return mkdir_one_if_missing(path, mode);
}

static int sync_send_stat(struct adb_stream *stream, const char *path)
{
	struct stat st;
	uint32_t out[4];

	memset(out, 0, sizeof(out));
	out[0] = S_ID_STAT;
	if (lstat(path, &st) == 0) {
		out[1] = (uint32_t)st.st_mode;
		out[2] = clamp_u32_off(st.st_size);
		out[3] = clamp_u32_time(st.st_mtime);
	}

	return stream_send(stream, out, sizeof(out));
}

static int sync_send_dent(struct adb_stream *stream, uint32_t id,
			  const struct stat *st, const char *name)
{
	unsigned char out[A_MAXDATA];
	uint32_t mode = st ? (uint32_t)st->st_mode : 0;
	uint32_t size = st ? clamp_u32_off(st->st_size) : 0;
	uint32_t mtime = st ? clamp_u32_time(st->st_mtime) : 0;
	uint32_t namelen = name ? (uint32_t)strlen(name) : 0;

	if (20U + namelen > sizeof(out))
		return 0;

	memcpy(out, &id, 4);
	memcpy(out + 4, &mode, 4);
	memcpy(out + 8, &size, 4);
	memcpy(out + 12, &mtime, 4);
	memcpy(out + 16, &namelen, 4);
	if (namelen)
		memcpy(out + 20, name, namelen);

	return stream_send(stream, out, 20U + namelen);
}

static int sync_handle_list(struct adb_stream *stream, const char *path)
{
	DIR *dir = opendir(path);
	struct dirent *de;

	if (!dir)
		return sync_send_dent(stream, S_ID_DONE, NULL, "");

	while ((de = readdir(dir)) && !stream->closed) {
		char full[PATH_MAX * 2];
		struct stat st;

		if (strcmp(de->d_name, ".") == 0 ||
		    strcmp(de->d_name, "..") == 0)
			continue;
		if (snprintf(full, sizeof(full), "%s/%s", path, de->d_name) >=
		    (int)sizeof(full))
			continue;
		if (lstat(full, &st) < 0)
			continue;
		if (sync_send_dent(stream, S_ID_DENT, &st, de->d_name) < 0) {
			closedir(dir);
			return -1;
		}
	}
	closedir(dir);

	return sync_send_dent(stream, S_ID_DONE, NULL, "");
}

static int sync_handle_recv(struct adb_stream *stream, const char *path)
{
	unsigned char out[A_MAXDATA];
	int fd = open(path, O_RDONLY | O_CLOEXEC);

	if (fd < 0)
		return sync_send_fail(stream, strerror(errno));

	while (!stream->closed) {
		ssize_t n = read(fd, out + 8, SYNC_DATA_MAX);
		uint32_t id = S_ID_DATA;
		uint32_t size;

		if (n < 0) {
			if (errno == EINTR)
				continue;
			close(fd);
			return sync_send_fail(stream, strerror(errno));
		}
		if (n == 0)
			break;

		size = (uint32_t)n;
		memcpy(out, &id, 4);
		memcpy(out + 4, &size, 4);
		if (stream_send(stream, out, 8U + (size_t)n) < 0) {
			close(fd);
			return -1;
		}
	}
	close(fd);

	return sync_send_status(stream, S_ID_DONE, "");
}

static int sync_discard_send(struct adb_stream *stream)
{
	unsigned char buf[A_MAXDATA];

	while (!stream->closed) {
		uint32_t hdr[2];
		uint32_t remaining;

		if (stream_read_exact(stream, hdr, sizeof(hdr)) < 0)
			return -1;
		if (hdr[0] == S_ID_DONE)
			return 0;
		if (hdr[0] != S_ID_DATA)
			return -1;
		remaining = hdr[1];
		while (remaining > 0) {
			size_t chunk = remaining > sizeof(buf) ?
				       sizeof(buf) : remaining;

			if (stream_read_exact(stream, buf, chunk) < 0)
				return -1;
			remaining -= (uint32_t)chunk;
		}
	}

	return -1;
}

static int sync_handle_send(struct adb_stream *stream, char *spec)
{
	char *comma = strrchr(spec, ',');
	const char *path = spec;
	mode_t mode = S_IFREG | 0644;
	int fd = -1;
	int saved_errno = 0;
	uint32_t mtime = 0;

	if (comma) {
		*comma = '\0';
		mode = (mode_t)strtoul(comma + 1, NULL, 0);
		if ((mode & S_IFMT) == 0)
			mode |= S_IFREG;
	}
	if (!path[0]) {
		sync_discard_send(stream);
		return sync_send_fail(stream, "empty path");
	}

	if (S_ISDIR(mode)) {
		if (mkdir_p_path(path, mode & 07777) < 0)
			saved_errno = errno;
		if (sync_discard_send(stream) < 0)
			return -1;
		if (!saved_errno) {
			chmod(path, mode & 07777);
			return sync_send_okay(stream);
		}
		errno = saved_errno;
		return sync_send_fail(stream, strerror(errno));
	}

	fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, mode & 07777);
	if (fd < 0 && errno == ENOENT && mkdir_p_parent(path) == 0)
		fd = open(path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC,
			  mode & 07777);
	if (fd < 0)
		saved_errno = errno;

	while (!stream->closed) {
		uint32_t hdr[2];
		uint32_t remaining;

		if (stream_read_exact(stream, hdr, sizeof(hdr)) < 0) {
			if (fd >= 0)
				close(fd);
			return -1;
		}
		if (hdr[0] == S_ID_DONE) {
			mtime = hdr[1];
			break;
		}
		if (hdr[0] != S_ID_DATA) {
			if (fd >= 0)
				close(fd);
			return sync_send_fail(stream, "unexpected sync packet");
		}

		remaining = hdr[1];
		while (remaining > 0) {
			unsigned char buf[A_MAXDATA];
			size_t chunk = remaining > sizeof(buf) ?
				       sizeof(buf) : remaining;

			if (stream_read_exact(stream, buf, chunk) < 0) {
				if (fd >= 0)
					close(fd);
				return -1;
			}
			if (fd >= 0 && !saved_errno &&
			    write_full(fd, buf, chunk) < 0)
				saved_errno = errno;
			remaining -= (uint32_t)chunk;
		}
	}

	if (fd >= 0) {
		if (!saved_errno && fsync(fd) < 0)
			saved_errno = errno;
		if (close(fd) < 0 && !saved_errno)
			saved_errno = errno;
	}

	if (!saved_errno) {
		struct utimbuf times;

		chmod(path, mode & 07777);
		if (mtime) {
			times.actime = (time_t)mtime;
			times.modtime = (time_t)mtime;
			utime(path, &times);
		}
		return sync_send_okay(stream);
	}

	errno = saved_errno;
	return sync_send_fail(stream, strerror(errno));
}

static int handle_sync_service(int fd, uint32_t remote_id)
{
	struct adb_stream stream = {
		.fd = fd,
		.local_id = SHELL_LOCAL_ID,
		.remote_id = remote_id,
	};

	while (keep_running && !stream.closed) {
		uint32_t hdr[2];
		char *path = NULL;
		int ret = 0;

		if (stream_read_exact(&stream, hdr, sizeof(hdr)) < 0)
			break;
		if (hdr[0] == S_ID_QUIT)
			break;
		if (sync_read_path(&stream, hdr[1], &path) < 0) {
			sync_send_fail(&stream, "bad path");
			break;
		}

		switch (hdr[0]) {
		case S_ID_STAT:
			ret = sync_send_stat(&stream, path);
			break;
		case S_ID_LIST:
			ret = sync_handle_list(&stream, path);
			break;
		case S_ID_RECV:
			ret = sync_handle_recv(&stream, path);
			break;
		case S_ID_SEND:
			ret = sync_handle_send(&stream, path);
			break;
		default:
			ret = sync_send_fail(&stream, "unsupported sync command");
			break;
		}

		free(path);
		if (ret < 0)
			break;
	}

	stream_close(&stream);
	return 0;
}

static void trigger_reboot(const char *target)
{
	pid_t pid = fork();

	if (pid != 0)
		return;

	sleep(1);
	if (target && (!strcmp(target, "bootloader") ||
		       !strcmp(target, "fastboot"))) {
		execl("/sbin/nq-reboot-fastboot", "nq-reboot-fastboot",
		      (char *)NULL);
		execl("/sbin/reboot-bootloader", "reboot-bootloader",
		      (char *)NULL);
	}
	execl("/sbin/reboot", "reboot", (char *)NULL);
	execl("/bin/busybox", "busybox", "reboot", (char *)NULL);
	_exit(127);
}

static int handle_text_service(int fd, uint32_t remote_id, const char *text)
{
	struct adb_stream stream = {
		.fd = fd,
		.local_id = SHELL_LOCAL_ID,
		.remote_id = remote_id,
	};

	if (text && text[0])
		stream_send(&stream, text, strlen(text));
	stream_close(&stream);
	return 0;
}

static int handle_transport(int fd)
{
	static const char banner[] =
		"device::ro.product.name=nexusq;"
		"ro.product.model=Nexus Q;"
		"ro.product.device=steelhead;"
		"features=";
	unsigned char data[A_MAXDATA + 1];
	struct adb_msg msg;
	uint32_t remote_id = 0;
	bool channel_open = false;
	bool can_send = true;
	int pty_fd = -1;
	pid_t shell_pid = -1;

	while (keep_running) {
		int ret = adb_recv(fd, &msg, data, sizeof(data) - 1);

		if (ret <= 0)
			return -1;
		if (msg.command == A_CNXN)
			break;
	}

	if (adb_send(fd, A_CNXN, A_VERSION, A_MAXDATA, banner,
		     sizeof(banner)) < 0)
		return -1;

	while (keep_running) {
		fd_set rfds;
		int maxfd = fd;
		int ret;

		FD_ZERO(&rfds);
		FD_SET(fd, &rfds);
		if (channel_open && can_send && pty_fd >= 0) {
			FD_SET(pty_fd, &rfds);
			if (pty_fd > maxfd)
				maxfd = pty_fd;
		}

		ret = select(maxfd + 1, &rfds, NULL, NULL, NULL);
		if (ret < 0) {
			if (errno == EINTR) {
				reap_child(shell_pid);
				continue;
			}
			break;
		}

		if (pty_fd >= 0 && FD_ISSET(pty_fd, &rfds)) {
			ssize_t n = read(pty_fd, data, A_MAXDATA);

			if (n > 0) {
				if (adb_send(fd, A_WRTE, SHELL_LOCAL_ID,
					     remote_id, data, (size_t)n) < 0)
					break;
				can_send = false;
			} else {
				adb_send(fd, A_CLSE, SHELL_LOCAL_ID, remote_id,
					 NULL, 0);
				channel_open = false;
				close(pty_fd);
				pty_fd = -1;
			}
		}

		if (!FD_ISSET(fd, &rfds))
			continue;

		ret = adb_recv(fd, &msg, data, sizeof(data) - 1);
		if (ret <= 0)
			break;

		switch (msg.command) {
		case A_OPEN: {
			const char *service = (char *)data;
			const char *cmd = shell_command_from_service(service);

			if (channel_open) {
				adb_send(fd, A_CLSE, 0, msg.arg0, NULL, 0);
				break;
			}
			remote_id = msg.arg0;

			if (strcmp(service, "sync:") == 0 ||
			    strcmp(service, "sync") == 0) {
				adb_send(fd, A_OKAY, SHELL_LOCAL_ID,
					 remote_id, NULL, 0);
				handle_sync_service(fd, remote_id);
				break;
			}
			if (strncmp(service, "reboot:", 7) == 0) {
				const char *target = service + 7;

				adb_send(fd, A_OKAY, SHELL_LOCAL_ID,
					 remote_id, NULL, 0);
				handle_text_service(fd, remote_id, "");
				trigger_reboot(target);
				break;
			}
			if (strcmp(service, "root:") == 0) {
				adb_send(fd, A_OKAY, SHELL_LOCAL_ID,
					 remote_id, NULL, 0);
				handle_text_service(fd, remote_id,
						    "adbd is already running as root\n");
				break;
			}
			if (!cmd) {
				adb_send(fd, A_CLSE, 0, msg.arg0, NULL, 0);
				break;
			}

			shell_pid = spawn_shell(&pty_fd, cmd);
			if (shell_pid < 0) {
				static const char fail[] = "failed to spawn shell\n";

				adb_send(fd, A_OKAY, SHELL_LOCAL_ID, remote_id,
					 NULL, 0);
				adb_send(fd, A_WRTE, SHELL_LOCAL_ID, remote_id,
					 fail, sizeof(fail) - 1);
				adb_send(fd, A_CLSE, SHELL_LOCAL_ID, remote_id,
					 NULL, 0);
				break;
			}
			channel_open = true;
			can_send = true;
			adb_send(fd, A_OKAY, SHELL_LOCAL_ID, remote_id,
				 NULL, 0);
		} break;
		case A_OKAY:
			can_send = true;
			break;
		case A_WRTE:
			if (channel_open && pty_fd >= 0) {
				adb_send(fd, A_OKAY, SHELL_LOCAL_ID, remote_id,
					 NULL, 0);
				if (msg.data_length)
					write_full(pty_fd, data,
						   msg.data_length);
			} else {
				adb_send(fd, A_CLSE, SHELL_LOCAL_ID, msg.arg0,
					 NULL, 0);
			}
			break;
		case A_CLSE:
			channel_open = false;
			if (pty_fd >= 0) {
				close(pty_fd);
				pty_fd = -1;
			}
			if (shell_pid > 0) {
				kill(shell_pid, SIGHUP);
				reap_child(shell_pid);
				shell_pid = -1;
			}
			break;
		case A_SYNC:
			break;
		default:
			break;
		}

		reap_child(shell_pid);
	}

	if (pty_fd >= 0)
		close(pty_fd);
	if (shell_pid > 0) {
		kill(shell_pid, SIGHUP);
		waitpid(shell_pid, NULL, 0);
	}

	return 0;
}

static int make_listener(int port)
{
	int fd;
	int one = 1;
	struct sockaddr_in addr;

	fd = socket(AF_INET, SOCK_STREAM, 0);
	if (fd < 0)
		return -1;
	setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));

	memset(&addr, 0, sizeof(addr));
	addr.sin_family = AF_INET;
	addr.sin_addr.s_addr = htonl(INADDR_ANY);
	addr.sin_port = htons((uint16_t)port);

	if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0 ||
	    listen(fd, 4) < 0) {
		close(fd);
		return -1;
	}

	return fd;
}

int main(int argc, char **argv)
{
	int port = ADB_PORT;
	int listener;

	if (argc > 1)
		port = atoi(argv[1]);
	if (port <= 0 || port > 65535) {
		fprintf(stderr, "usage: %s [port]\n", argv[0]);
		return 2;
	}

	signal(SIGINT, on_signal);
	signal(SIGTERM, on_signal);
	signal(SIGHUP, SIG_IGN);
	signal(SIGCHLD, SIG_IGN);

	listener = make_listener(port);
	if (listener < 0) {
		perror("listen");
		return 1;
	}

	fprintf(stderr, "nq-adbd-lite listening on tcp:%d\n", port);
	while (keep_running) {
		struct sockaddr_in peer;
		socklen_t peer_len = sizeof(peer);
		int fd = accept(listener, (struct sockaddr *)&peer, &peer_len);

		if (fd < 0) {
			if (errno == EINTR)
				continue;
			perror("accept");
			break;
		}

		handle_transport(fd);
		close(fd);
	}

	close(listener);
	return 0;
}
