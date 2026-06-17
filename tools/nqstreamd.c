#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#include <tinyalsa/asoundlib.h>

#define ID_RIFF 0x46464952
#define ID_WAVE 0x45564157
#define ID_FMT  0x20746d66
#define ID_DATA 0x61746164
#define FORMAT_PCM 1
#define TAS5713_SET_MASTER_VOLUME _IOW('A', 0xF9, uint8_t)

struct wav_fmt {
	uint16_t audio_format;
	uint16_t channels;
	uint32_t rate;
	uint32_t byte_rate;
	uint16_t block_align;
	uint16_t bits_per_sample;
};

static int read_exact(int fd, void *buf, size_t len)
{
	char *p = buf;
	while (len > 0) {
		ssize_t n = read(fd, p, len);
		if (n == 0)
			return -1;
		if (n < 0) {
			if (errno == EINTR)
				continue;
			return -1;
		}
		p += n;
		len -= (size_t)n;
	}
	return 0;
}

static int skip_bytes(int fd, uint32_t len)
{
	char buf[512];
	while (len > 0) {
		size_t want = len < sizeof(buf) ? len : sizeof(buf);
		if (read_exact(fd, buf, want))
			return -1;
		len -= (uint32_t)want;
	}
	return 0;
}

static int read_wav_header(int fd, struct wav_fmt *fmt, uint32_t *data_size)
{
	uint32_t header[3];
	int have_fmt = 0;

	if (read_exact(fd, header, sizeof(header)))
		return -1;
	if (header[0] != ID_RIFF || header[2] != ID_WAVE)
		return -1;

	for (;;) {
		uint32_t chunk[2];
		uint32_t id;
		uint32_t size;

		if (read_exact(fd, chunk, sizeof(chunk)))
			return -1;

		id = chunk[0];
		size = chunk[1];

		if (id == ID_FMT) {
			if (size < 16)
				return -1;
			if (read_exact(fd, fmt, sizeof(*fmt)))
				return -1;
			if (size > sizeof(*fmt) && skip_bytes(fd, size - sizeof(*fmt)))
				return -1;
			if (size & 1 && skip_bytes(fd, 1))
				return -1;
			have_fmt = 1;
			continue;
		}

		if (id == ID_DATA) {
			if (!have_fmt)
				return -1;
			*data_size = size;
			return 0;
		}

		if (skip_bytes(fd, size))
			return -1;
		if (size & 1 && skip_bytes(fd, 1))
			return -1;
	}
}

static int pcm_write_all(struct pcm *pcm, const void *buffer, unsigned int bytes,
			 int noirq_mmap)
{
	if (noirq_mmap)
		return pcm_mmap_write(pcm, (void *)buffer, bytes);

	return pcm_write(pcm, (void *)buffer, bytes);
}

static int stream_client(int client_fd, unsigned int card, unsigned int device,
			 int tas5713_volume, int noirq_mmap)
{
	struct wav_fmt fmt;
	struct pcm_config config;
	struct pcm *pcm;
	char *buffer;
	unsigned int buffer_size;
	unsigned int frame_size;
	uint32_t remaining;
	int rc = 1;

	if (read_wav_header(client_fd, &fmt, &remaining)) {
		fprintf(stderr, "invalid or unsupported WAV header\n");
		return 1;
	}

	if (fmt.audio_format != FORMAT_PCM || (fmt.bits_per_sample != 16 && fmt.bits_per_sample != 32)) {
		fprintf(stderr, "unsupported WAV format: format=%u bits=%u\n",
			fmt.audio_format, fmt.bits_per_sample);
		return 1;
	}

	memset(&config, 0, sizeof(config));
	config.channels = fmt.channels;
	config.rate = fmt.rate;
	config.period_size = 1024;
	config.period_count = 4;
	config.format = fmt.bits_per_sample == 32 ? PCM_FORMAT_S32_LE : PCM_FORMAT_S16_LE;
	if (noirq_mmap) {
		config.start_threshold = config.period_size * config.period_count;
		config.avail_min = config.period_size;
	}

	pcm = pcm_open(card, device,
		       PCM_OUT | (noirq_mmap ? (PCM_MMAP | PCM_NOIRQ) : 0),
		       &config);
	if (!pcm || !pcm_is_ready(pcm)) {
		fprintf(stderr, "unable to open PCM card %u device %u (%s)\n",
			card, device, pcm_get_error(pcm));
		return 1;
	}

	if (tas5713_volume >= 0) {
		uint8_t volume = (uint8_t)tas5713_volume;

		if (pcm_ioctl(pcm, TAS5713_SET_MASTER_VOLUME, &volume) < 0) {
			fprintf(stderr, "TAS5713_SET_MASTER_VOLUME 0x%02x failed: %s\n",
				volume, strerror(errno));
			pcm_close(pcm);
			return 1;
		}
		printf("set TAS5713 private master volume: 0x%02x\n", volume);
	}

	frame_size = fmt.channels * (fmt.bits_per_sample / 8);
	buffer_size = pcm_frames_to_bytes(pcm, pcm_get_buffer_size(pcm));
	buffer = malloc(buffer_size);
	if (!buffer) {
		fprintf(stderr, "unable to allocate %u bytes\n", buffer_size);
		pcm_close(pcm);
		return 1;
	}

	printf("streaming WAV: card=%u device=%u channels=%u rate=%u bits=%u bytes=%u\n",
	       card, device, fmt.channels, fmt.rate, fmt.bits_per_sample, remaining);
	if (noirq_mmap)
		printf("using tinyalsa PCM_MMAP|PCM_NOIRQ period_size=%u periods=%u\n",
		       config.period_size, config.period_count);
	fflush(stdout);

	while (remaining > 0) {
		unsigned int want = remaining < buffer_size ? remaining : buffer_size;

		if (want < frame_size) {
			fprintf(stderr, "dropping trailing partial frame: %u bytes\n", want);
			if (skip_bytes(client_fd, want))
				break;
			remaining = 0;
			continue;
		}

		want -= want % frame_size;
		if (read_exact(client_fd, buffer, want)) {
			fprintf(stderr, "client closed early\n");
			break;
		}
		if (pcm_write_all(pcm, buffer, want, noirq_mmap)) {
			fprintf(stderr, "pcm_write failed: %s\n", pcm_get_error(pcm));
			break;
		}
		remaining -= want;
	}

	if (remaining == 0)
		rc = 0;

	free(buffer);
	pcm_close(pcm);
	return rc;
}

static int listen_socket(unsigned int port)
{
	int fd;
	int on = 1;
	int v6only = 0;
	struct sockaddr_in6 addr;

	fd = socket(AF_INET6, SOCK_STREAM, 0);
	if (fd < 0) {
		perror("socket");
		return -1;
	}
	setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &on, sizeof(on));
	setsockopt(fd, IPPROTO_IPV6, IPV6_V6ONLY, &v6only, sizeof(v6only));

	memset(&addr, 0, sizeof(addr));
	addr.sin6_family = AF_INET6;
	addr.sin6_addr = in6addr_any;
	addr.sin6_port = htons((uint16_t)port);

	if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
		perror("bind");
		close(fd);
		return -1;
	}
	if (listen(fd, 4) < 0) {
		perror("listen");
		close(fd);
		return -1;
	}
	return fd;
}

int main(int argc, char **argv)
{
	unsigned int port = 5555;
	unsigned int card = 2;
	unsigned int device = 0;
	int tas5713_volume = -1;
	int once = 0;
	int noirq_mmap = 0;
	int fd;
	int i;

	for (i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "-p") && i + 1 < argc) {
			port = (unsigned int)strtoul(argv[++i], NULL, 0);
		} else if (!strcmp(argv[i], "-c") && i + 1 < argc) {
			card = (unsigned int)strtoul(argv[++i], NULL, 0);
		} else if (!strcmp(argv[i], "-d") && i + 1 < argc) {
			device = (unsigned int)strtoul(argv[++i], NULL, 0);
		} else if (!strcmp(argv[i], "--tas5713-volume") && i + 1 < argc) {
			unsigned long value = strtoul(argv[++i], NULL, 0);
			if (value > 0xff) {
				fprintf(stderr, "TAS5713 volume must be 0..255\n");
				return 1;
			}
			tas5713_volume = (int)value;
		} else if (!strcmp(argv[i], "--once")) {
			once = 1;
		} else if (!strcmp(argv[i], "--noirq-mmap")) {
			noirq_mmap = 1;
		} else {
			fprintf(stderr,
				"Usage: %s [-p port] [-c card] [-d device] [--tas5713-volume value] [--once] [--noirq-mmap]\n",
				argv[0]);
			return 1;
		}
	}

	signal(SIGPIPE, SIG_IGN);
	setvbuf(stdout, NULL, _IOLBF, 0);

	fd = listen_socket(port);
	if (fd < 0)
		return 1;

	printf("nqstreamd listening on [::]:%u -> ALSA card %u device %u\n", port, card, device);
	if (tas5713_volume >= 0)
		printf("TAS5713 private master volume will be set to 0x%02x per stream\n",
		       (unsigned int)tas5713_volume);
	if (noirq_mmap)
		printf("PCM streams will request no-period-wakeup mmap mode\n");

	for (;;) {
		struct sockaddr_in6 peer;
		socklen_t peer_len = sizeof(peer);
		int client = accept(fd, (struct sockaddr *)&peer, &peer_len);
		if (client < 0) {
			if (errno == EINTR)
				continue;
			perror("accept");
			break;
		}
		stream_client(client, card, device, tas5713_volume, noirq_mmap);
		close(client);
		if (once)
			break;
	}

	close(fd);
	return 0;
}
