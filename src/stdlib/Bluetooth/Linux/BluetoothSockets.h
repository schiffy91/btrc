#pragma once

#include <errno.h>
#include <poll.h>
#include <stdint.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

/* The kernel's Bluetooth socket ABI. Its structures and numbers live in
 * BlueZ's library headers, not the kernel's exported ones, so the few this
 * needs are spelled here and each socket call that takes one is an adapter.
 * Addresses are six bytes, last byte of the written form first. */
#define BTRC_BTPROTO_L2CAP 0
#define BTRC_SOL_BLUETOOTH 274
#define BTRC_BT_SECURITY 4

struct BtrcL2CAPAddress {
	sa_family_t family;
	uint16_t psm;
	uint8_t address[6];
	uint16_t channel;
	uint8_t addressType;
};

struct BtrcBluetoothSecurity {
	uint8_t level;
	uint8_t keySize;
};

static inline void btrcL2CAPFill(struct BtrcL2CAPAddress* out, unsigned char* address, int psm) {
	memset(out, 0, sizeof(*out));
	out->family = AF_BLUETOOTH;
	out->psm = (uint16_t)psm;
	memcpy(out->address, address, 6);
}

/* A nonblocking, close-on-exec L2CAP socket that keeps packet boundaries. */
static inline int btrcL2CAPSocket(void) { return socket(AF_BLUETOOTH, SOCK_SEQPACKET | SOCK_NONBLOCK | SOCK_CLOEXEC, BTRC_BTPROTO_L2CAP); }

/* Bind to an adapter's address (all zero for any) and a PSM (0 for none). */
static inline int btrcL2CAPBind(int descriptor, unsigned char* address, int psm) {
	struct BtrcL2CAPAddress local;
	btrcL2CAPFill(&local, address, psm);
	return bind(descriptor, (struct sockaddr*)&local, sizeof(local));
}

static inline int btrcL2CAPListen(int descriptor) { return listen(descriptor, 4); }

/* Start connecting; 0, or -1 with errno (EINPROGRESS while it proceeds). */
static inline int btrcL2CAPConnect(int descriptor, unsigned char* address, int psm) {
	struct BtrcL2CAPAddress remote;
	btrcL2CAPFill(&remote, address, psm);
	return connect(descriptor, (struct sockaddr*)&remote, sizeof(remote));
}

/* Accept one channel; its socket, with the peer's address in `peer`. */
static inline int btrcL2CAPAccept(int descriptor, unsigned char* peer) {
	struct BtrcL2CAPAddress remote;
	socklen_t length = sizeof(remote);
	memset(&remote, 0, sizeof(remote));
	int accepted = accept4(descriptor, (struct sockaddr*)&remote, &length, SOCK_NONBLOCK | SOCK_CLOEXEC);
	if (accepted >= 0) { memcpy(peer, remote.address, 6); }
	return accepted;
}

/* Require a security level (1 none, 2 encrypted, 3 authenticated) on a channel. */
static inline int btrcL2CAPSecurity(int descriptor, int level) {
	struct BtrcBluetoothSecurity security;
	security.level = (uint8_t)level;
	security.keySize = 0;
	return setsockopt(descriptor, BTRC_SOL_BLUETOOTH, BTRC_BT_SECURITY, &security, sizeof(security));
}

/* The pending error of a socket whose connect finished; 0 for none. */
static inline int btrcL2CAPError(int descriptor) {
	int failure = 0;
	socklen_t length = sizeof(failure);
	if (getsockopt(descriptor, SOL_SOCKET, SO_ERROR, &failure, &length) != 0) { return errno; }
	return failure;
}

/* Send ahead of other traffic on the adapter. */
static inline int btrcL2CAPPriority(int descriptor, int priority) { return setsockopt(descriptor, SOL_SOCKET, SO_PRIORITY, &priority, sizeof(priority)); }

/* Bytes waiting to be sent: what the socket's send buffer holds. Bluetooth
 * sockets report the free space, so this is the buffer's size less that. */
static inline int btrcL2CAPUnsent(int descriptor) {
	int size = 0;
	int space = 0;
	socklen_t length = sizeof(size);
	if (getsockopt(descriptor, SOL_SOCKET, SO_SNDBUF, &size, &length) != 0 || ioctl(descriptor, TIOCOUTQ, &space) != 0) { return 0; }
	return size > space ? size - space : 0;
}

/* Whether the kernel can create L2CAP sockets at all. */
static inline int btrcL2CAPAvailable(void) {
	int descriptor = btrcL2CAPSocket();
	if (descriptor < 0) { return 0; }
	close(descriptor);
	return 1;
}
