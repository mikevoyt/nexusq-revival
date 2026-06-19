// SPDX-License-Identifier: GPL-2.0-only
/*
 * Nexus Q front-panel AVR I2C debug helper.
 *
 * This is intentionally small and uses I2C_SLAVE_FORCE so bring-up can inspect
 * and poke the AVR while the kernel driver owns the normal I2C client. Avoid
 * long-running direct I2C sessions while steelhead_avr.ko is polling.
 */

#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#ifndef I2C_SLAVE_FORCE
#define I2C_SLAVE_FORCE 0x0706
#endif

#define DEFAULT_DEV "/dev/i2c-1"
#define DEFAULT_ADDR 0x20
#define MAX_I2C_ATTEMPTS 5

static void usage(const char *argv0)
{
	fprintf(stderr,
		"usage:\n"
		"  %s dump [dev] [addr]\n"
		"  %s read <reg> [len] [dev] [addr]\n"
		"  %s write-byte <reg> <val> [dev] [addr]\n"
		"  %s write-block <reg> <val>... [-- dev addr]\n"
		"  %s mode <0|1|2|3> [dev] [addr]\n"
		"  %s fifo [count] [delay-ms] [dev] [addr]\n",
		argv0, argv0, argv0, argv0, argv0, argv0);
}

static int parse_u8(const char *s, uint8_t *out)
{
	char *end = NULL;
	long value;

	errno = 0;
	value = strtol(s, &end, 0);
	if (errno || !end || *end || value < 0 || value > 255)
		return -1;

	*out = (uint8_t)value;
	return 0;
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

static int open_avr(const char *dev, int addr)
{
	int fd = open(dev, O_RDWR | O_CLOEXEC);

	if (fd < 0) {
		fprintf(stderr, "open %s failed: %s\n", dev, strerror(errno));
		return -1;
	}

	if (ioctl(fd, I2C_SLAVE_FORCE, addr) < 0) {
		fprintf(stderr, "I2C_SLAVE_FORCE 0x%02x failed: %s\n",
			addr, strerror(errno));
		close(fd);
		return -1;
	}

	return fd;
}

static int avr_read(int fd, uint8_t reg, uint8_t *buf, size_t len)
{
	ssize_t ret;
	int i;

	for (i = 0; i < MAX_I2C_ATTEMPTS; i++) {
		ret = write(fd, &reg, 1);
		if (ret == 1)
			break;
		usleep(1000);
	}
	if (ret != 1)
		return -1;

	usleep(100);
	for (i = 0; i < MAX_I2C_ATTEMPTS; i++) {
		ret = read(fd, buf, len);
		if (ret == (ssize_t)len)
			break;
		usleep(1000);
	}
	if (ret != (ssize_t)len)
		return -1;

	return 0;
}

static int avr_write(int fd, uint8_t reg, const uint8_t *buf, size_t len)
{
	uint8_t out[34];
	ssize_t ret;

	if (len > sizeof(out) - 1)
		return -1;

	out[0] = reg;
	memcpy(&out[1], buf, len);
	for (int i = 0; i < MAX_I2C_ATTEMPTS; i++) {
		ret = write(fd, out, len + 1);
		if (ret == (ssize_t)(len + 1))
			break;
		usleep(1000);
	}
	if (ret != (ssize_t)(len + 1))
		return -1;

	return 0;
}

static void print_bytes(uint8_t reg, const uint8_t *buf, size_t len)
{
	size_t i;

	printf("0x%02x:", reg);
	for (i = 0; i < len; i++)
		printf(" 0x%02x", buf[i]);
	putchar('\n');
}

static int cmd_dump(int fd)
{
	uint8_t val;
	int reg;
	int rc = 0;

	for (reg = 0; reg <= 0x0a; reg++) {
		if (avr_read(fd, (uint8_t)reg, &val, 1) < 0) {
			printf("0x%02x: read failed\n", reg);
			rc = 1;
			continue;
		}
		print_bytes((uint8_t)reg, &val, 1);
	}

	return rc;
}

static int cmd_fifo(int fd, int count, int delay_ms)
{
	int i;

	for (i = 0; i < count; i++) {
		uint8_t val = 0xff;

		if (avr_read(fd, 0x00, &val, 1) < 0) {
			fprintf(stderr, "fifo read failed: %s\n", strerror(errno));
			return 1;
		}
		printf("%03d: 0x%02x\n", i, val);
		fflush(stdout);
		if (delay_ms > 0)
			usleep((useconds_t)delay_ms * 1000U);
	}

	return 0;
}

int main(int argc, char **argv)
{
	const char *cmd;
	const char *dev = DEFAULT_DEV;
	int addr = DEFAULT_ADDR;
	int fd;
	int rc = 0;

	if (argc < 2) {
		usage(argv[0]);
		return 2;
	}

	cmd = argv[1];

	if (strcmp(cmd, "dump") == 0) {
		if (argc > 2)
			dev = argv[2];
		if (argc > 3 && parse_int(argv[3], 0, 0x7f, &addr) < 0)
			return 2;
		fd = open_avr(dev, addr);
		if (fd < 0)
			return 1;
		rc = cmd_dump(fd);
		close(fd);
		return rc;
	}

	if (strcmp(cmd, "read") == 0) {
		uint8_t reg;
		uint8_t buf[32];
		int len = 1;

		if (argc < 3 || parse_u8(argv[2], &reg) < 0)
			return 2;
		if (argc > 3 && parse_int(argv[3], 1, (int)sizeof(buf), &len) < 0)
			return 2;
		if (argc > 4)
			dev = argv[4];
		if (argc > 5 && parse_int(argv[5], 0, 0x7f, &addr) < 0)
			return 2;
		fd = open_avr(dev, addr);
		if (fd < 0)
			return 1;
		rc = avr_read(fd, reg, buf, (size_t)len) < 0 ? 1 : 0;
		if (!rc)
			print_bytes(reg, buf, (size_t)len);
		close(fd);
		return rc;
	}

	if (strcmp(cmd, "write-byte") == 0 || strcmp(cmd, "mode") == 0) {
		uint8_t reg = 0x02;
		uint8_t val;

		if (strcmp(cmd, "write-byte") == 0) {
			if (argc < 4 || parse_u8(argv[2], &reg) < 0 ||
			    parse_u8(argv[3], &val) < 0)
				return 2;
			if (argc > 4)
				dev = argv[4];
			if (argc > 5 && parse_int(argv[5], 0, 0x7f, &addr) < 0)
				return 2;
		} else {
			if (argc < 3 || parse_u8(argv[2], &val) < 0 || val > 3)
				return 2;
			if (argc > 3)
				dev = argv[3];
			if (argc > 4 && parse_int(argv[4], 0, 0x7f, &addr) < 0)
				return 2;
		}

		fd = open_avr(dev, addr);
		if (fd < 0)
			return 1;
		rc = avr_write(fd, reg, &val, 1) < 0 ? 1 : 0;
		close(fd);
		return rc;
	}

	if (strcmp(cmd, "write-block") == 0) {
		uint8_t reg;
		uint8_t vals[32];
		int count = 0;
		int i;

		if (argc < 4 || parse_u8(argv[2], &reg) < 0)
			return 2;
		for (i = 3; i < argc; i++) {
			if (strcmp(argv[i], "--") == 0) {
				if (i + 1 < argc)
					dev = argv[i + 1];
				if (i + 2 < argc &&
				    parse_int(argv[i + 2], 0, 0x7f, &addr) < 0)
					return 2;
				break;
			}
			if (count >= (int)sizeof(vals) || parse_u8(argv[i], &vals[count]) < 0)
				return 2;
			count++;
		}
		if (count == 0)
			return 2;

		fd = open_avr(dev, addr);
		if (fd < 0)
			return 1;
		rc = avr_write(fd, reg, vals, (size_t)count) < 0 ? 1 : 0;
		close(fd);
		return rc;
	}

	if (strcmp(cmd, "fifo") == 0) {
		int count = 20;
		int delay_ms = 50;

		if (argc > 2 && parse_int(argv[2], 1, 10000, &count) < 0)
			return 2;
		if (argc > 3 && parse_int(argv[3], 0, 10000, &delay_ms) < 0)
			return 2;
		if (argc > 4)
			dev = argv[4];
		if (argc > 5 && parse_int(argv[5], 0, 0x7f, &addr) < 0)
			return 2;
		fd = open_avr(dev, addr);
		if (fd < 0)
			return 1;
		rc = cmd_fifo(fd, count, delay_ms);
		close(fd);
		return rc;
	}

	usage(argv[0]);
	return 2;
}
