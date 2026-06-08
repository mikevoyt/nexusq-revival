typedef unsigned int size_t;

#define SYS_EXIT 1
#define SYS_READ 3
#define SYS_WRITE 4
#define SYS_OPEN 5
#define SYS_CLOSE 6
#define SYS_UNLINK 10
#define SYS_IOCTL 54

#define O_RDONLY 0
#define O_WRONLY 1

#define RNDADDENTROPY 0x40085203UL

struct rand_pool_info_64 {
	int entropy_count;
	int buf_size;
	unsigned char buf[128];
};

static long syscall1(long nr, long a0)
{
	register long r0 __asm__("r0") = a0;
	register long r7 __asm__("r7") = nr;

	__asm__ volatile("svc #0" : "+r"(r0) : "r"(r7) : "memory", "cc");
	return r0;
}

static long syscall2(long nr, long a0, long a1)
{
	register long r0 __asm__("r0") = a0;
	register long r1 __asm__("r1") = a1;
	register long r7 __asm__("r7") = nr;

	__asm__ volatile("svc #0" : "+r"(r0) : "r"(r1), "r"(r7) : "memory", "cc");
	return r0;
}

static long syscall3(long nr, long a0, long a1, long a2)
{
	register long r0 __asm__("r0") = a0;
	register long r1 __asm__("r1") = a1;
	register long r2 __asm__("r2") = a2;
	register long r7 __asm__("r7") = nr;

	__asm__ volatile("svc #0" : "+r"(r0) : "r"(r1), "r"(r2), "r"(r7) : "memory", "cc");
	return r0;
}

static void say(const char *s)
{
	size_t n = 0;

	while (s[n])
		n++;
	syscall3(SYS_WRITE, 2, (long)s, n);
}

void _start(void)
{
	static const char seed_path[] = "/tmp/rng.seed";
	static const char random_path[] = "/dev/random";
	struct rand_pool_info_64 pool;
	long seed_fd;
	long random_fd;
	long n;
	long rc;
	int i;

	for (i = 0; i < (int)sizeof(pool.buf); i++)
		pool.buf[i] = 0;

	seed_fd = syscall3(SYS_OPEN, (long)seed_path, O_RDONLY, 0);
	if (seed_fd < 0) {
		say("seed-rng: cannot open /tmp/rng.seed\n");
		syscall1(SYS_EXIT, 2);
	}

	n = syscall3(SYS_READ, seed_fd, (long)pool.buf, sizeof(pool.buf));
	syscall1(SYS_CLOSE, seed_fd);
	if (n < 32) {
		say("seed-rng: seed too short\n");
		syscall1(SYS_EXIT, 3);
	}

	random_fd = syscall3(SYS_OPEN, (long)random_path, O_WRONLY, 0);
	if (random_fd < 0) {
		say("seed-rng: cannot open /dev/random\n");
		syscall1(SYS_EXIT, 4);
	}

	pool.buf_size = (int)n;
	pool.entropy_count = (int)n * 4;
	if (pool.entropy_count > 512)
		pool.entropy_count = 512;

	rc = syscall3(SYS_IOCTL, random_fd, RNDADDENTROPY, (long)&pool);
	syscall1(SYS_CLOSE, random_fd);
	syscall1(SYS_UNLINK, (long)seed_path);

	if (rc < 0) {
		say("seed-rng: RNDADDENTROPY failed\n");
		syscall1(SYS_EXIT, 5);
	}

	say("seed-rng: credited entropy\n");
	syscall1(SYS_EXIT, 0);
}
