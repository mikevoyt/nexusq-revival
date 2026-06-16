/*
 * Tiny no-libc ARM Linux helper for the vendor Nexus Q 3.0 TAS5713 driver.
 *
 * The old codec driver stores the master volume through a private PCM ioctl:
 *   TAS5713_SET_MASTER_VOLUME _IOW('A', 0xF9, __u8)
 *
 * This program exists so we can build a standalone ARM EABI binary on macOS
 * with arm-none-eabi-gcc and run it in the small 3.0 rescue image without
 * depending on libc, ALSA, or the i386 Linux cross toolchain.
 */

typedef unsigned int uint32_t;
typedef unsigned char uint8_t;

#define SYS_exit  1
#define SYS_write 4
#define SYS_open  5
#define SYS_close 6
#define SYS_ioctl 54

#define O_RDWR 2

#define TAS5713_SET_MASTER_VOLUME 0x400141f9UL

static long syscall0(long nr)
{
	register long r7 asm("r7") = nr;
	register long r0 asm("r0");

	asm volatile("svc 0" : "=r"(r0) : "r"(r7) : "memory");
	return r0;
}

static long syscall1(long nr, long a0)
{
	register long r7 asm("r7") = nr;
	register long r0 asm("r0") = a0;

	asm volatile("svc 0" : "+r"(r0) : "r"(r7) : "memory");
	return r0;
}

static long syscall3(long nr, long a0, long a1, long a2)
{
	register long r7 asm("r7") = nr;
	register long r0 asm("r0") = a0;
	register long r1 asm("r1") = a1;
	register long r2 asm("r2") = a2;

	asm volatile("svc 0"
		     : "+r"(r0)
		     : "r"(r1), "r"(r2), "r"(r7)
		     : "memory");
	return r0;
}

static unsigned int cstr_len(const char *s)
{
	unsigned int len = 0;

	while (s[len])
		len++;
	return len;
}

static void write_all(int fd, const char *s)
{
	(void)syscall3(SYS_write, fd, (long)s, cstr_len(s));
}

static void write_hex8(uint8_t value)
{
	static const char hex[] = "0123456789abcdef";
	char out[] = "0x00";

	out[2] = hex[(value >> 4) & 0xf];
	out[3] = hex[value & 0xf];
	write_all(1, out);
}

static int parse_u8(const char *s, uint8_t *out)
{
	unsigned int value = 0;
	unsigned int base = 10;
	unsigned int i = 0;

	if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
		base = 16;
		i = 2;
	}

	if (!s[i])
		return -1;

	for (; s[i]; i++) {
		unsigned int digit;

		if (s[i] >= '0' && s[i] <= '9')
			digit = (unsigned int)(s[i] - '0');
		else if (s[i] >= 'a' && s[i] <= 'f')
			digit = 10U + (unsigned int)(s[i] - 'a');
		else if (s[i] >= 'A' && s[i] <= 'F')
			digit = 10U + (unsigned int)(s[i] - 'A');
		else
			return -1;

		if (digit >= base)
			return -1;
		value = (value * base) + digit;
		if (value > 255)
			return -1;
	}

	*out = (uint8_t)value;
	return 0;
}

static int main_start(uint32_t *sp)
{
	int argc = (int)sp[0];
	const char **argv = (const char **)&sp[1];
	const char *path = "/dev/snd/pcmC2D0p";
	uint8_t volume = 0x50;
	long fd;
	long ret;

	if (argc > 1 && parse_u8(argv[1], &volume)) {
		write_all(2, "usage: nq-tas5713-volume [volume] [pcm]\n");
		syscall1(SYS_exit, 2);
	}
	if (argc > 2)
		path = argv[2];

	fd = syscall3(SYS_open, (long)path, O_RDWR, 0);
	if (fd < 0) {
		write_all(2, "open failed\n");
		syscall1(SYS_exit, 1);
	}

	ret = syscall3(SYS_ioctl, fd, TAS5713_SET_MASTER_VOLUME,
		       (long)&volume);
	(void)syscall1(SYS_close, fd);

	if (ret < 0) {
		write_all(2, "TAS5713_SET_MASTER_VOLUME failed\n");
		syscall1(SYS_exit, 1);
	}

	write_all(1, "set TAS5713 master volume ");
	write_hex8(volume);
	write_all(1, "\n");
	syscall1(SYS_exit, 0);

	return 0;
}

__attribute__((naked, noreturn)) void _start(void)
{
	asm volatile("mov r0, sp\n"
		     "b main_start\n");
	__builtin_unreachable();
}

