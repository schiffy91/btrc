#ifndef BTRC_STDLIB_HTTP_CLIENT_SOCKETS_H
#define BTRC_STDLIB_HTTP_CLIENT_SOCKETS_H

/* SDK includes for the client's BSD-socket connection. The typed binding
 * imports the resolver, which the hosted ABI does not carry. */
#include <errno.h>
#include <netdb.h>
#include <netinet/in.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

/* 0 transfers the result to the caller, -1 means timeout, -2 lookup failure. */
int btrcHttpResolve(const char *host, const char *service, long long deadlineMs, struct addrinfo **result);

#endif
