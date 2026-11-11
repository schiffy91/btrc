#ifndef BTRC_STDLIB_NETWORK_SOCKETS_H
#define BTRC_STDLIB_NETWORK_SOCKETS_H

/* SDK includes for the BSD-socket bodies of TCPStream and TCPListener. The
 * typed binding imports the declarations the hosted ABI does not carry. */
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

#endif
