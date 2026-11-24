#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "Peer.h"
#include <poll.h>
#include <stdio.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

static int channel = -1;

int acceptFramePeer(void) {
	struct sockaddr_un address = {.sun_family = AF_UNIX, .sun_path = "frame-peer.pending"};
	int listener = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
	if (listener < 0) { return -1; }
	int pid = -1;
	if (!bind(listener, (struct sockaddr *)&address, sizeof address) && !listen(listener, 1)
	    && !rename(address.sun_path, "frame-peer")) {
		struct pollfd ready = {.fd = listener, .events = POLLIN};
		if (poll(&ready, 1, 30000) == 1) {
			channel = accept4(listener, NULL, NULL, SOCK_CLOEXEC);
			struct ucred peer;
			socklen_t size = sizeof peer;
			if (channel >= 0 && !getsockopt(channel, SOL_SOCKET, SO_PEERCRED, &peer, &size) && peer.uid == getuid()) {
				pid = peer.pid;
			} else { closeFramePeer(); }
		}
	}
	close(listener);
	unlink("frame-peer");
	unlink(address.sun_path);
	return pid;
}

int submitFrame(const char *address, int width, int pattern) {
	char command[128];
	int count = snprintf(command, sizeof command, "%s %d %d", address, width, pattern);
	if (count <= 0 || (size_t)count >= sizeof command || send(channel, command, count, MSG_NOSIGNAL) != count) { return -1; }
	struct pollfd response = {.fd = channel, .events = POLLIN};
	unsigned char result;
	if (poll(&response, 1, 10000) != 1 || recv(channel, &result, 1, 0) != 1) { return -1; }
	return result;
}

void closeFramePeer(void) {
	if (channel >= 0) { close(channel); channel = -1; }
}
