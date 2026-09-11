#pragma once
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#include <poll.h>
#include <fcntl.h>
#include <errno.h>

typedef struct sockaddr_un LocalSocketAddress;

/* Normalize the two SDK credential layouts, not ownership policy. The caller
 * compares the returned user ID and owns the descriptor. No resource escapes. */
static inline int localSocketPeerUser(int descriptor, uid_t* user) {
#if defined(__APPLE__)
    gid_t group;
    return getpeereid(descriptor, user, &group);
#elif defined(__linux__)
    struct ucred credentials;
    socklen_t size = sizeof(credentials);
    if (getsockopt(descriptor, SOL_SOCKET, SO_PEERCRED, &credentials, &size) != 0) { return -1; }
    if (size != sizeof(credentials)) { errno = EIO; return -1; }
    *user = credentials.uid;
    return 0;
#else
#error Unsupported local socket credential ABI
#endif
}
