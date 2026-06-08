#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef LINUX_REBOOT_MAGIC1
#define LINUX_REBOOT_MAGIC1 0xfee1dead
#endif

#ifndef LINUX_REBOOT_MAGIC2
#define LINUX_REBOOT_MAGIC2 672274793
#endif

#ifndef LINUX_REBOOT_CMD_RESTART2
#define LINUX_REBOOT_CMD_RESTART2 0xa1b2c3d4
#endif

int main(int argc, char **argv)
{
	const char *target = argc > 1 ? argv[1] : "bootloader";
	long rc;

	printf("rebooting with restart command '%s'\n", target);
	fflush(stdout);
	sync();

	rc = syscall(SYS_reboot, LINUX_REBOOT_MAGIC1, LINUX_REBOOT_MAGIC2,
		     LINUX_REBOOT_CMD_RESTART2, target);
	if (rc < 0)
		fprintf(stderr, "reboot syscall failed: %s\n", strerror(errno));

	return rc < 0 ? 1 : 0;
}
