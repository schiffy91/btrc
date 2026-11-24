#ifndef BTRC_STDLIB_HTTP_CLIENT_SOCKETS_H
#define BTRC_STDLIB_HTTP_CLIENT_SOCKETS_H

/* The resolver owns the SDK-specific addrinfo layout. Its callers keep
 * the list alive until they have finished trying the returned addresses. */
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
int btrcHttpResolve(char *host, char *service, long long deadlineMs, void **result);

int btrcHttpSocksAddress(char *host, int local, int onlyIPv4, long long deadline, char *output);
int btrcHttpAddressSocket(void **cursor, struct sockaddr **address, socklen_t *length);
void btrcHttpFreeAddresses(void *addresses);

#endif
