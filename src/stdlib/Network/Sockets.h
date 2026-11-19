#ifndef BTRC_STDLIB_NETWORK_SOCKETS_H
#define BTRC_STDLIB_NETWORK_SOCKETS_H

/* SDK includes for the BSD-socket bodies of TCPStream and TCPListener, and the
 * two options whose names differ between systems. The typed binding imports
 * the declarations the hosted ABI does not carry. */
#include <arpa/inet.h>
#include <errno.h>
#include <limits.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

/* The idle time before the first probe is TCP_KEEPIDLE on Linux and Android
 * and TCP_KEEPALIVE on Apple's systems; the other two are named alike. */
static inline int btrcSocketKeepAliveTiming(int descriptor, int idleSeconds, int intervalSeconds, int probes) {
#if defined(TCP_KEEPIDLE)
	int idle = TCP_KEEPIDLE;
#else
	int idle = TCP_KEEPALIVE;
#endif
	if (setsockopt(descriptor, IPPROTO_TCP, idle, &idleSeconds, sizeof(idleSeconds)) != 0) { return -1; }
	if (setsockopt(descriptor, IPPROTO_TCP, TCP_KEEPINTVL, &intervalSeconds, sizeof(intervalSeconds)) != 0) { return -1; }
	return setsockopt(descriptor, IPPROTO_TCP, TCP_KEEPCNT, &probes, sizeof(probes));
}

/* How long sent data may stay unacknowledged before the connection is
 * dropped: TCP_USER_TIMEOUT in milliseconds on Linux, TCP_RXT_CONNDROPTIME in
 * whole seconds on Apple's systems. -1 where the system has neither. */
static inline int btrcSocketUnacknowledgedTimeout(int descriptor, int milliseconds) {
#if defined(TCP_USER_TIMEOUT)
	unsigned int limit = (unsigned int)milliseconds;
	return setsockopt(descriptor, IPPROTO_TCP, TCP_USER_TIMEOUT, &limit, sizeof(limit));
#elif defined(TCP_RXT_CONNDROPTIME)
	int seconds = (milliseconds + 999) / 1000;
	return setsockopt(descriptor, IPPROTO_TCP, TCP_RXT_CONNDROPTIME, &seconds, sizeof(seconds));
#else
	(void)descriptor;
	(void)milliseconds;
	return -1;
#endif
}

#endif
