// SPDX-License-Identifier: GPL-2.0-only
/*
 * Minimal Linux NFC generic-netlink poller for the Nexus Q PN544.
 *
 * This intentionally avoids a neard dependency. It powers the first kernel NFC
 * device, starts an initiator poll, waits for the kernel targets-found event,
 * dumps the target list, and prints NFCID1/ISO15693 UIDs for shell scripts.
 */

#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <linux/genetlink.h>
#include <linux/netlink.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#ifndef NETLINK_GENERIC
#define NETLINK_GENERIC 16
#endif

#ifndef SOL_NETLINK
#define SOL_NETLINK 270
#endif

#ifndef GENL_ID_CTRL
#define GENL_ID_CTRL NLMSG_MIN_TYPE
#endif

#ifndef GENL_HDRLEN
#define GENL_HDRLEN NLMSG_ALIGN(sizeof(struct genlmsghdr))
#endif

#ifndef NLA_HDRLEN
struct nlattr {
	uint16_t nla_len;
	uint16_t nla_type;
};
#define NLA_ALIGNTO 4
#define NLA_ALIGN(len) (((len) + NLA_ALIGNTO - 1) & ~(NLA_ALIGNTO - 1))
#define NLA_HDRLEN ((int)NLA_ALIGN(sizeof(struct nlattr)))
#endif

#ifndef NLA_TYPE_MASK
#define NLA_TYPE_MASK 0x3fff
#endif

#define NFC_GENL_NAME "nfc"
#define NFC_GENL_VERSION 1
#define NFC_GENL_MCAST_EVENT_NAME "events"

enum nfc_commands_local {
	NFC_CMD_UNSPEC_LOCAL,
	NFC_CMD_GET_DEVICE,
	NFC_CMD_DEV_UP,
	NFC_CMD_DEV_DOWN,
	NFC_CMD_DEP_LINK_UP,
	NFC_CMD_DEP_LINK_DOWN,
	NFC_CMD_START_POLL,
	NFC_CMD_STOP_POLL,
	NFC_CMD_GET_TARGET,
	NFC_EVENT_TARGETS_FOUND,
	NFC_EVENT_DEVICE_ADDED,
	NFC_EVENT_DEVICE_REMOVED,
	NFC_EVENT_TARGET_LOST,
	NFC_EVENT_TM_ACTIVATED,
	NFC_EVENT_TM_DEACTIVATED,
};

enum nfc_attrs_local {
	NFC_ATTR_UNSPEC_LOCAL,
	NFC_ATTR_DEVICE_INDEX,
	NFC_ATTR_DEVICE_NAME,
	NFC_ATTR_PROTOCOLS,
	NFC_ATTR_TARGET_INDEX,
	NFC_ATTR_TARGET_SENS_RES,
	NFC_ATTR_TARGET_SEL_RES,
	NFC_ATTR_TARGET_NFCID1,
	NFC_ATTR_TARGET_SENSB_RES,
	NFC_ATTR_TARGET_SENSF_RES,
	NFC_ATTR_COMM_MODE,
	NFC_ATTR_RF_MODE,
	NFC_ATTR_DEVICE_POWERED,
	NFC_ATTR_IM_PROTOCOLS,
	NFC_ATTR_TM_PROTOCOLS,
	NFC_ATTR_LLC_PARAM_LTO,
	NFC_ATTR_LLC_PARAM_RW,
	NFC_ATTR_LLC_PARAM_MIUX,
	NFC_ATTR_SE,
	NFC_ATTR_LLC_SDP,
	NFC_ATTR_FIRMWARE_NAME,
	NFC_ATTR_SE_INDEX,
	NFC_ATTR_SE_TYPE,
	NFC_ATTR_SE_AID,
	NFC_ATTR_FIRMWARE_DOWNLOAD_STATUS,
	NFC_ATTR_SE_APDU,
	NFC_ATTR_TARGET_ISO15693_DSFID,
	NFC_ATTR_TARGET_ISO15693_UID,
	NFC_ATTR_SE_PARAMS,
	NFC_ATTR_VENDOR_ID,
	NFC_ATTR_VENDOR_SUBCMD,
	NFC_ATTR_VENDOR_DATA,
	NFC_ATTR_MAX_LOCAL = NFC_ATTR_VENDOR_DATA,
};

#define NFC_PROTO_JEWEL_MASK      (1U << 1)
#define NFC_PROTO_MIFARE_MASK     (1U << 2)
#define NFC_PROTO_FELICA_MASK     (1U << 3)
#define NFC_PROTO_ISO14443_MASK   (1U << 4)
#define NFC_PROTO_NFC_DEP_MASK    (1U << 5)
#define NFC_PROTO_ISO14443_B_MASK (1U << 6)
#define NFC_PROTO_ISO15693_MASK   (1U << 7)

#define DEFAULT_PROTOCOLS \
	(NFC_PROTO_JEWEL_MASK | NFC_PROTO_MIFARE_MASK | \
	 NFC_PROTO_ISO14443_MASK | NFC_PROTO_ISO14443_B_MASK | \
	 NFC_PROTO_FELICA_MASK | NFC_PROTO_ISO15693_MASK)

#define RECV_BUF_SIZE 8192
#define SEND_BUF_SIZE 1024
#define MAX_DEVICES 8
#define MAX_TARGETS 16

struct nl_attr_spec {
	uint16_t type;
	const void *data;
	size_t len;
};

struct nfc_family {
	uint16_t id;
	uint32_t events_group;
};

struct nfc_device {
	uint32_t idx;
	uint32_t protocols;
	uint8_t powered;
	char name[32];
};

struct nfc_target {
	uint32_t idx;
	uint32_t protocols;
	uint16_t sens_res;
	uint8_t sel_res;
	uint8_t nfcid1[10];
	size_t nfcid1_len;
	uint8_t iso15693_uid[8];
	size_t iso15693_uid_len;
};

static uint32_t nl_seq;
static int verbose;

static void usage(const char *argv0)
{
	fprintf(stderr,
		"usage: %s [--timeout seconds] [--device index] [--protocols mask] [--list] [-v]\n",
		argv0);
}

static long long monotonic_ms(void)
{
	struct timespec ts;

	if (clock_gettime(CLOCK_MONOTONIC, &ts) < 0)
		return 0;
	return (long long)ts.tv_sec * 1000LL + ts.tv_nsec / 1000000LL;
}

static uint32_t attr_u32(const struct nlattr *attr)
{
	uint32_t value = 0;

	if (attr && attr->nla_len >= NLA_HDRLEN + sizeof(value))
		memcpy(&value, (const char *)attr + NLA_HDRLEN, sizeof(value));
	return value;
}

static uint16_t attr_u16(const struct nlattr *attr)
{
	uint16_t value = 0;

	if (attr && attr->nla_len >= NLA_HDRLEN + sizeof(value))
		memcpy(&value, (const char *)attr + NLA_HDRLEN, sizeof(value));
	return value;
}

static uint8_t attr_u8(const struct nlattr *attr)
{
	uint8_t value = 0;

	if (attr && attr->nla_len >= NLA_HDRLEN + sizeof(value))
		memcpy(&value, (const char *)attr + NLA_HDRLEN, sizeof(value));
	return value;
}

static const void *attr_data(const struct nlattr *attr)
{
	return attr ? (const char *)attr + NLA_HDRLEN : NULL;
}

static size_t attr_len(const struct nlattr *attr)
{
	if (!attr || attr->nla_len < NLA_HDRLEN)
		return 0;
	return attr->nla_len - NLA_HDRLEN;
}

static void parse_attrs(struct nlattr **tb, int maxattr, void *data, int len)
{
	struct nlattr *attr;

	memset(tb, 0, sizeof(tb[0]) * (size_t)(maxattr + 1));
	for (attr = data;
	     len >= NLA_HDRLEN && attr->nla_len >= NLA_HDRLEN &&
		     attr->nla_len <= len;
	     len -= NLA_ALIGN(attr->nla_len),
	     attr = (struct nlattr *)((char *)attr + NLA_ALIGN(attr->nla_len))) {
		int type = attr->nla_type & NLA_TYPE_MASK;

		if (type <= maxattr)
			tb[type] = attr;
	}
}

static int add_attr(struct nlmsghdr *nlh, size_t maxlen, uint16_t type,
		    const void *data, size_t len)
{
	size_t pos = NLMSG_ALIGN(nlh->nlmsg_len);
	size_t attr_len_total = NLA_HDRLEN + len;
	size_t padded = NLA_ALIGN(attr_len_total);
	struct nlattr *attr;

	if (pos + padded > maxlen)
		return -1;

	attr = (struct nlattr *)((char *)nlh + pos);
	attr->nla_type = type;
	attr->nla_len = (uint16_t)attr_len_total;
	if (len)
		memcpy((char *)attr + NLA_HDRLEN, data, len);
	if (padded > attr_len_total)
		memset((char *)attr + attr_len_total, 0, padded - attr_len_total);
	nlh->nlmsg_len = (uint32_t)(pos + padded);
	return 0;
}

static int nl_open(void)
{
	struct timeval tv = {
		.tv_sec = 1,
		.tv_usec = 0,
	};
	struct sockaddr_nl local;
	int fd;

	fd = socket(AF_NETLINK, SOCK_RAW, NETLINK_GENERIC);
	if (fd < 0) {
		perror("socket NETLINK_GENERIC");
		return -1;
	}

	memset(&local, 0, sizeof(local));
	local.nl_family = AF_NETLINK;
	if (bind(fd, (struct sockaddr *)&local, sizeof(local)) < 0) {
		perror("bind netlink");
		close(fd);
		return -1;
	}

	setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
	return fd;
}

static int nl_send_cmd(int fd, uint16_t family, uint8_t cmd, uint16_t flags,
		       const struct nl_attr_spec *attrs, size_t nattrs,
		       uint32_t *seq_out)
{
	struct sockaddr_nl kernel;
	unsigned char buf[SEND_BUF_SIZE];
	struct nlmsghdr *nlh = (struct nlmsghdr *)buf;
	struct genlmsghdr *ghdr;
	uint32_t seq = ++nl_seq;

	memset(buf, 0, sizeof(buf));
	nlh->nlmsg_len = NLMSG_HDRLEN + GENL_HDRLEN;
	nlh->nlmsg_type = family;
	nlh->nlmsg_flags = (uint16_t)(flags | NLM_F_REQUEST);
	nlh->nlmsg_seq = seq;
	nlh->nlmsg_pid = (uint32_t)getpid();

	ghdr = (struct genlmsghdr *)NLMSG_DATA(nlh);
	ghdr->cmd = cmd;
	ghdr->version = NFC_GENL_VERSION;
	ghdr->reserved = 0;

	for (size_t i = 0; i < nattrs; i++) {
		if (add_attr(nlh, sizeof(buf), attrs[i].type, attrs[i].data,
			     attrs[i].len) < 0) {
			fprintf(stderr, "nq-nfc-poll: request too large\n");
			return -1;
		}
	}

	memset(&kernel, 0, sizeof(kernel));
	kernel.nl_family = AF_NETLINK;
	if (sendto(fd, nlh, nlh->nlmsg_len, 0, (struct sockaddr *)&kernel,
		   sizeof(kernel)) < 0) {
		perror("sendto netlink");
		return -1;
	}

	if (seq_out)
		*seq_out = seq;
	return 0;
}

static int recv_ack(int fd, uint32_t seq, const char *what)
{
	unsigned char buf[RECV_BUF_SIZE];

	for (;;) {
		ssize_t len = recv(fd, buf, sizeof(buf), 0);
		struct nlmsghdr *nlh;

		if (len < 0) {
			if (errno == EINTR)
				continue;
			if (errno == EAGAIN || errno == EWOULDBLOCK) {
				fprintf(stderr, "nq-nfc-poll: timeout waiting for %s ack\n",
					what);
				return ETIMEDOUT;
			}
			perror("recv netlink ack");
			return errno ? errno : EIO;
		}

		for (nlh = (struct nlmsghdr *)buf; NLMSG_OK(nlh, len);
		     nlh = NLMSG_NEXT(nlh, len)) {
			if (nlh->nlmsg_seq != seq)
				continue;
			if (nlh->nlmsg_type == NLMSG_ERROR) {
				struct nlmsgerr *err = (struct nlmsgerr *)NLMSG_DATA(nlh);

				if (err->error == 0)
					return 0;
				return -err->error;
			}
		}
	}
}

static int resolve_nfc_family(int fd, struct nfc_family *family)
{
	struct nl_attr_spec attr;
	uint32_t seq;
	unsigned char buf[RECV_BUF_SIZE];

	memset(family, 0, sizeof(*family));
	attr.type = CTRL_ATTR_FAMILY_NAME;
	attr.data = NFC_GENL_NAME;
	attr.len = strlen(NFC_GENL_NAME) + 1;
	if (nl_send_cmd(fd, GENL_ID_CTRL, CTRL_CMD_GETFAMILY, 0, &attr, 1,
			&seq) < 0)
		return -1;

	for (;;) {
		ssize_t len = recv(fd, buf, sizeof(buf), 0);
		struct nlmsghdr *nlh;

		if (len < 0) {
			if (errno == EINTR)
				continue;
			fprintf(stderr, "nq-nfc-poll: cannot resolve kernel NFC netlink family\n");
			return -1;
		}

		for (nlh = (struct nlmsghdr *)buf; NLMSG_OK(nlh, len);
		     nlh = NLMSG_NEXT(nlh, len)) {
			struct genlmsghdr *ghdr;
			struct nlattr *attrs[CTRL_ATTR_MAX + 1];
			int payload_len;

			if (nlh->nlmsg_seq != seq)
				continue;
			if (nlh->nlmsg_type == NLMSG_ERROR) {
				struct nlmsgerr *err = (struct nlmsgerr *)NLMSG_DATA(nlh);

				errno = err->error ? -err->error : ENOENT;
				perror("nq-nfc-poll: NFC netlink family lookup failed");
				return -1;
			}
			if (nlh->nlmsg_type != GENL_ID_CTRL)
				continue;

			ghdr = (struct genlmsghdr *)NLMSG_DATA(nlh);
			payload_len = (int)nlh->nlmsg_len - NLMSG_HDRLEN - GENL_HDRLEN;
			if (payload_len < 0)
				continue;
			parse_attrs(attrs, CTRL_ATTR_MAX,
				    (char *)ghdr + GENL_HDRLEN, payload_len);
			if (!attrs[CTRL_ATTR_FAMILY_ID])
				continue;

			family->id = attr_u16(attrs[CTRL_ATTR_FAMILY_ID]);
			if (attrs[CTRL_ATTR_MCAST_GROUPS]) {
				struct nlattr *grp;
				int rem = (int)attr_len(attrs[CTRL_ATTR_MCAST_GROUPS]);

				for (grp = (struct nlattr *)attr_data(attrs[CTRL_ATTR_MCAST_GROUPS]);
				     rem >= NLA_HDRLEN && grp->nla_len >= NLA_HDRLEN &&
					     grp->nla_len <= rem;
				     rem -= NLA_ALIGN(grp->nla_len),
				     grp = (struct nlattr *)((char *)grp + NLA_ALIGN(grp->nla_len))) {
					struct nlattr *gattrs[CTRL_ATTR_MCAST_GRP_MAX + 1];
					const char *name;

					parse_attrs(gattrs, CTRL_ATTR_MCAST_GRP_MAX,
						    (char *)grp + NLA_HDRLEN,
						    (int)grp->nla_len - NLA_HDRLEN);
					if (!gattrs[CTRL_ATTR_MCAST_GRP_NAME] ||
					    !gattrs[CTRL_ATTR_MCAST_GRP_ID])
						continue;
					name = attr_data(gattrs[CTRL_ATTR_MCAST_GRP_NAME]);
					if (name && strcmp(name, NFC_GENL_MCAST_EVENT_NAME) == 0)
						family->events_group = attr_u32(gattrs[CTRL_ATTR_MCAST_GRP_ID]);
				}
			}

			if (verbose)
				fprintf(stderr, "nq-nfc-poll: family=%u events_group=%u\n",
					family->id, family->events_group);
			return 0;
		}
	}
}

static int join_events_group(int fd, const struct nfc_family *family)
{
	uint32_t group = family->events_group;

	if (!group)
		return 0;
	if (setsockopt(fd, SOL_NETLINK, NETLINK_ADD_MEMBERSHIP, &group,
		       sizeof(group)) < 0) {
		if (verbose)
			perror("nq-nfc-poll: NETLINK_ADD_MEMBERSHIP events");
		return -1;
	}
	return 0;
}

static void copy_attr_string(char *dest, size_t dest_len, const struct nlattr *attr)
{
	size_t len;

	if (!dest_len)
		return;
	dest[0] = '\0';
	if (!attr)
		return;
	len = attr_len(attr);
	if (len >= dest_len)
		len = dest_len - 1;
	memcpy(dest, attr_data(attr), len);
	dest[len] = '\0';
}

static int get_devices(int fd, const struct nfc_family *family,
		       struct nfc_device *devices, size_t max_devices)
{
	uint32_t seq;
	unsigned char buf[RECV_BUF_SIZE];
	size_t count = 0;

	if (nl_send_cmd(fd, family->id, NFC_CMD_GET_DEVICE, NLM_F_DUMP,
			NULL, 0, &seq) < 0)
		return -1;

	for (;;) {
		ssize_t len = recv(fd, buf, sizeof(buf), 0);
		struct nlmsghdr *nlh;

		if (len < 0) {
			if (errno == EINTR)
				continue;
			fprintf(stderr, "nq-nfc-poll: timeout waiting for NFC device list\n");
			return -1;
		}

		for (nlh = (struct nlmsghdr *)buf; NLMSG_OK(nlh, len);
		     nlh = NLMSG_NEXT(nlh, len)) {
			struct genlmsghdr *ghdr;
			struct nlattr *attrs[NFC_ATTR_MAX_LOCAL + 1];
			int payload_len;

			if (nlh->nlmsg_seq != seq)
				continue;
			if (nlh->nlmsg_type == NLMSG_DONE)
				return (int)count;
			if (nlh->nlmsg_type == NLMSG_ERROR) {
				struct nlmsgerr *err = (struct nlmsgerr *)NLMSG_DATA(nlh);

				errno = err->error ? -err->error : EIO;
				perror("nq-nfc-poll: NFC device dump failed");
				return -1;
			}
			if (nlh->nlmsg_type != family->id)
				continue;
			ghdr = (struct genlmsghdr *)NLMSG_DATA(nlh);
			if (ghdr->cmd != NFC_CMD_GET_DEVICE)
				continue;

			payload_len = (int)nlh->nlmsg_len - NLMSG_HDRLEN - GENL_HDRLEN;
			if (payload_len < 0)
				continue;
			parse_attrs(attrs, NFC_ATTR_MAX_LOCAL,
				    (char *)ghdr + GENL_HDRLEN, payload_len);
			if (!attrs[NFC_ATTR_DEVICE_INDEX] || count >= max_devices)
				continue;

			memset(&devices[count], 0, sizeof(devices[count]));
			devices[count].idx = attr_u32(attrs[NFC_ATTR_DEVICE_INDEX]);
			devices[count].protocols = attr_u32(attrs[NFC_ATTR_PROTOCOLS]);
			devices[count].powered = attr_u8(attrs[NFC_ATTR_DEVICE_POWERED]);
			copy_attr_string(devices[count].name, sizeof(devices[count].name),
					 attrs[NFC_ATTR_DEVICE_NAME]);
			count++;
		}
	}
}

static int command_ack_u32(int fd, const struct nfc_family *family,
			   uint8_t cmd, uint16_t attr_type, uint32_t value,
			   const char *what)
{
	struct nl_attr_spec attr = {
		.type = attr_type,
		.data = &value,
		.len = sizeof(value),
	};
	uint32_t seq;

	if (nl_send_cmd(fd, family->id, cmd, NLM_F_ACK, &attr, 1, &seq) < 0)
		return EIO;
	return recv_ack(fd, seq, what);
}

static int start_poll(int fd, const struct nfc_family *family, uint32_t dev_idx,
		      uint32_t protocols)
{
	struct nl_attr_spec attrs[2] = {
		{
			.type = NFC_ATTR_DEVICE_INDEX,
			.data = &dev_idx,
			.len = sizeof(dev_idx),
		},
		{
			.type = NFC_ATTR_IM_PROTOCOLS,
			.data = &protocols,
			.len = sizeof(protocols),
		},
	};
	uint32_t seq;

	if (nl_send_cmd(fd, family->id, NFC_CMD_START_POLL, NLM_F_ACK,
			attrs, 2, &seq) < 0)
		return EIO;
	return recv_ack(fd, seq, "start poll");
}

static int stop_poll(int fd, const struct nfc_family *family, uint32_t dev_idx)
{
	return command_ack_u32(fd, family, NFC_CMD_STOP_POLL,
			       NFC_ATTR_DEVICE_INDEX, dev_idx, "stop poll");
}

static void print_hex(const uint8_t *buf, size_t len)
{
	for (size_t i = 0; i < len; i++)
		printf("%02x", buf[i]);
}

static int get_targets(int fd, const struct nfc_family *family, uint32_t dev_idx,
		       struct nfc_target *targets, size_t max_targets)
{
	struct nl_attr_spec attr = {
		.type = NFC_ATTR_DEVICE_INDEX,
		.data = &dev_idx,
		.len = sizeof(dev_idx),
	};
	uint32_t seq;
	unsigned char buf[RECV_BUF_SIZE];
	size_t count = 0;

	if (nl_send_cmd(fd, family->id, NFC_CMD_GET_TARGET, NLM_F_DUMP,
			&attr, 1, &seq) < 0)
		return -1;

	for (;;) {
		ssize_t len = recv(fd, buf, sizeof(buf), 0);
		struct nlmsghdr *nlh;

		if (len < 0) {
			if (errno == EINTR)
				continue;
			fprintf(stderr, "nq-nfc-poll: timeout waiting for NFC target list\n");
			return -1;
		}

		for (nlh = (struct nlmsghdr *)buf; NLMSG_OK(nlh, len);
		     nlh = NLMSG_NEXT(nlh, len)) {
			struct genlmsghdr *ghdr;
			struct nlattr *attrs[NFC_ATTR_MAX_LOCAL + 1];
			int payload_len;

			if (nlh->nlmsg_seq != seq)
				continue;
			if (nlh->nlmsg_type == NLMSG_DONE)
				return (int)count;
			if (nlh->nlmsg_type == NLMSG_ERROR) {
				struct nlmsgerr *err = (struct nlmsgerr *)NLMSG_DATA(nlh);

				errno = err->error ? -err->error : EIO;
				perror("nq-nfc-poll: NFC target dump failed");
				return -1;
			}
			if (nlh->nlmsg_type != family->id || count >= max_targets)
				continue;
			ghdr = (struct genlmsghdr *)NLMSG_DATA(nlh);
			if (ghdr->cmd != NFC_CMD_GET_TARGET)
				continue;

			payload_len = (int)nlh->nlmsg_len - NLMSG_HDRLEN - GENL_HDRLEN;
			if (payload_len < 0)
				continue;
			parse_attrs(attrs, NFC_ATTR_MAX_LOCAL,
				    (char *)ghdr + GENL_HDRLEN, payload_len);
			if (!attrs[NFC_ATTR_TARGET_INDEX])
				continue;

			memset(&targets[count], 0, sizeof(targets[count]));
			targets[count].idx = attr_u32(attrs[NFC_ATTR_TARGET_INDEX]);
			targets[count].protocols = attr_u32(attrs[NFC_ATTR_PROTOCOLS]);
			targets[count].sens_res = attr_u16(attrs[NFC_ATTR_TARGET_SENS_RES]);
			targets[count].sel_res = attr_u8(attrs[NFC_ATTR_TARGET_SEL_RES]);
			if (attrs[NFC_ATTR_TARGET_NFCID1]) {
				targets[count].nfcid1_len = attr_len(attrs[NFC_ATTR_TARGET_NFCID1]);
				if (targets[count].nfcid1_len > sizeof(targets[count].nfcid1))
					targets[count].nfcid1_len = sizeof(targets[count].nfcid1);
				memcpy(targets[count].nfcid1,
				       attr_data(attrs[NFC_ATTR_TARGET_NFCID1]),
				       targets[count].nfcid1_len);
			}
			if (attrs[NFC_ATTR_TARGET_ISO15693_UID]) {
				targets[count].iso15693_uid_len =
					attr_len(attrs[NFC_ATTR_TARGET_ISO15693_UID]);
				if (targets[count].iso15693_uid_len >
				    sizeof(targets[count].iso15693_uid))
					targets[count].iso15693_uid_len =
						sizeof(targets[count].iso15693_uid);
				memcpy(targets[count].iso15693_uid,
				       attr_data(attrs[NFC_ATTR_TARGET_ISO15693_UID]),
				       targets[count].iso15693_uid_len);
			}
			count++;
		}
	}
}

static int wait_for_targets_event(int fd, const struct nfc_family *family,
				  uint32_t dev_idx, int timeout_ms)
{
	long long deadline = monotonic_ms() + timeout_ms;

	while (monotonic_ms() < deadline) {
		struct pollfd pfd = {
			.fd = fd,
			.events = POLLIN,
		};
		long long now = monotonic_ms();
		int wait_ms = (int)(deadline - now);
		unsigned char buf[RECV_BUF_SIZE];
		ssize_t len;
		struct nlmsghdr *nlh;
		int ret;

		if (wait_ms > 1000)
			wait_ms = 1000;
		if (wait_ms < 0)
			wait_ms = 0;

		ret = poll(&pfd, 1, wait_ms);
		if (ret < 0) {
			if (errno == EINTR)
				continue;
			perror("poll netlink");
			return -1;
		}
		if (ret == 0)
			continue;

		len = recv(fd, buf, sizeof(buf), 0);
		if (len < 0) {
			if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)
				continue;
			perror("recv netlink event");
			return -1;
		}

		for (nlh = (struct nlmsghdr *)buf; NLMSG_OK(nlh, len);
		     nlh = NLMSG_NEXT(nlh, len)) {
			struct genlmsghdr *ghdr;
			struct nlattr *attrs[NFC_ATTR_MAX_LOCAL + 1];
			int payload_len;

			if (nlh->nlmsg_type != family->id)
				continue;
			ghdr = (struct genlmsghdr *)NLMSG_DATA(nlh);
			if (ghdr->cmd != NFC_EVENT_TARGETS_FOUND)
				continue;
			payload_len = (int)nlh->nlmsg_len - NLMSG_HDRLEN - GENL_HDRLEN;
			if (payload_len < 0)
				continue;
			parse_attrs(attrs, NFC_ATTR_MAX_LOCAL,
				    (char *)ghdr + GENL_HDRLEN, payload_len);
			if (!attrs[NFC_ATTR_DEVICE_INDEX] ||
			    attr_u32(attrs[NFC_ATTR_DEVICE_INDEX]) != dev_idx)
				continue;
			return 1;
		}
	}

	return 0;
}

static int wait_for_targets_dump(int fd, const struct nfc_family *family,
				 uint32_t dev_idx, struct nfc_target *targets,
				 size_t max_targets, int timeout_ms)
{
	long long deadline = monotonic_ms() + timeout_ms;

	while (monotonic_ms() < deadline) {
		int n_targets = get_targets(fd, family, dev_idx, targets, max_targets);

		if (n_targets < 0)
			return n_targets;
		if (n_targets > 0)
			return n_targets;
		usleep(250000);
	}

	return 0;
}

static int parse_u32_arg(const char *s, uint32_t *out)
{
	char *end = NULL;
	unsigned long value;

	errno = 0;
	value = strtoul(s, &end, 0);
	if (errno || !end || *end || value > UINT32_MAX)
		return -1;
	*out = (uint32_t)value;
	return 0;
}

int main(int argc, char **argv)
{
	int timeout_sec = 15;
	bool list_only = false;
	bool device_set = false;
	uint32_t selected_device = 0;
	uint32_t requested_protocols = DEFAULT_PROTOCOLS;
	int fd = -1;
	struct nfc_family family;
	struct nfc_device devices[MAX_DEVICES];
	int n_devices;
	struct nfc_device *dev = NULL;
	uint32_t poll_protocols;
	bool event_subscribed = false;
	int rc = 1;

	for (int i = 1; i < argc; i++) {
		if (strcmp(argv[i], "--timeout") == 0) {
			char *end = NULL;
			long value;

			if (++i >= argc)
				return usage(argv[0]), 2;
			errno = 0;
			value = strtol(argv[i], &end, 0);
			if (errno || !end || *end || value < 1 || value > 300)
				return usage(argv[0]), 2;
			timeout_sec = (int)value;
		} else if (strcmp(argv[i], "--device") == 0) {
			if (++i >= argc || parse_u32_arg(argv[i], &selected_device) < 0)
				return usage(argv[0]), 2;
			device_set = true;
		} else if (strcmp(argv[i], "--protocols") == 0) {
			if (++i >= argc || parse_u32_arg(argv[i], &requested_protocols) < 0)
				return usage(argv[0]), 2;
		} else if (strcmp(argv[i], "--list") == 0) {
			list_only = true;
		} else if (strcmp(argv[i], "-v") == 0 || strcmp(argv[i], "--verbose") == 0) {
			verbose = 1;
		} else if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
			usage(argv[0]);
			return 0;
		} else {
			usage(argv[0]);
			return 2;
		}
	}

	fd = nl_open();
	if (fd < 0)
		return 1;

	if (resolve_nfc_family(fd, &family) < 0)
		goto out;

	n_devices = get_devices(fd, &family, devices, MAX_DEVICES);
	if (n_devices < 0)
		goto out;
	if (n_devices == 0) {
		fprintf(stderr, "nq-nfc-poll: no kernel NFC devices found\n");
		goto out;
	}

	for (int i = 0; i < n_devices; i++) {
		if (list_only) {
			printf("nq-nfc-poll: device index=%u name=%s protocols=0x%08x powered=%u\n",
			       devices[i].idx, devices[i].name[0] ? devices[i].name : "?",
			       devices[i].protocols, devices[i].powered);
		}
		if ((!device_set && !dev) ||
		    (device_set && devices[i].idx == selected_device)) {
			dev = &devices[i];
		}
	}
	if (list_only) {
		rc = 0;
		goto out;
	}
	if (!dev) {
		fprintf(stderr, "nq-nfc-poll: requested NFC device not found\n");
		goto out;
	}

	if (family.events_group && join_events_group(fd, &family) == 0)
		event_subscribed = true;
	else if (verbose)
		fprintf(stderr, "nq-nfc-poll: continuing without event subscription\n");

	if (verbose)
		fprintf(stderr, "nq-nfc-poll: using device index=%u name=%s protocols=0x%08x\n",
			dev->idx, dev->name[0] ? dev->name : "?", dev->protocols);

	poll_protocols = requested_protocols;
	if (dev->protocols)
		poll_protocols &= dev->protocols;
	if (!poll_protocols)
		poll_protocols = requested_protocols;

	rc = command_ack_u32(fd, &family, NFC_CMD_DEV_UP, NFC_ATTR_DEVICE_INDEX,
			     dev->idx, "device up");
	if (rc && rc != EALREADY) {
		errno = rc;
		perror("nq-nfc-poll: NFC device up failed");
		goto out;
	}

	rc = start_poll(fd, &family, dev->idx, poll_protocols);
	if (rc == EBUSY) {
		(void)stop_poll(fd, &family, dev->idx);
		rc = start_poll(fd, &family, dev->idx, poll_protocols);
	}
	if (rc) {
		errno = rc;
		perror("nq-nfc-poll: NFC start poll failed");
		goto out;
	}

	if (verbose)
		fprintf(stderr, "nq-nfc-poll: waiting up to %d seconds for a tag\n",
			timeout_sec);

	{
		struct nfc_target targets[MAX_TARGETS];
		int n_targets;

		if (event_subscribed) {
			rc = wait_for_targets_event(fd, &family, dev->idx,
						    timeout_sec * 1000);
			if (rc <= 0) {
				if (rc == 0)
					fprintf(stderr, "nq-nfc-poll: no tag found before timeout\n");
				(void)stop_poll(fd, &family, dev->idx);
				rc = 1;
				goto out;
			}
			n_targets = get_targets(fd, &family, dev->idx, targets, MAX_TARGETS);
		} else {
			n_targets = wait_for_targets_dump(fd, &family, dev->idx,
							  targets, MAX_TARGETS,
							  timeout_sec * 1000);
		}
		if (n_targets < 0) {
			rc = 1;
			goto out;
		}
		if (n_targets == 0) {
			fprintf(stderr, "nq-nfc-poll: no tag found before timeout\n");
			(void)stop_poll(fd, &family, dev->idx);
			rc = 1;
			goto out;
		}

		for (int i = 0; i < n_targets; i++) {
			printf("nq-nfc-poll: target index=%u protocols=0x%08x sens_res=0x%04x sel_res=0x%02x\n",
			       targets[i].idx, targets[i].protocols,
			       targets[i].sens_res, targets[i].sel_res);
			if (targets[i].nfcid1_len) {
				printf("nq-nfc-poll: uid=");
				print_hex(targets[i].nfcid1, targets[i].nfcid1_len);
				putchar('\n');
				rc = 0;
				goto out;
			}
			if (targets[i].iso15693_uid_len) {
				printf("nq-nfc-poll: iso15693_uid=");
				print_hex(targets[i].iso15693_uid,
					  targets[i].iso15693_uid_len);
				putchar('\n');
				rc = 0;
				goto out;
			}
		}
	}

	fprintf(stderr, "nq-nfc-poll: tag found without printable UID\n");
	rc = 1;

out:
	if (fd >= 0)
		close(fd);
	return rc;
}
