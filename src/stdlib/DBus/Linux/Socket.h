#pragma once

/* SDK includes for the Unix-domain socket the D-Bus transport is. The typed
 * binding imports the socket address, which the hosted ABI does not carry. */
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <poll.h>
#include <pwd.h>
#include <sys/stat.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/un.h>
#include <sys/uio.h>
#include <unistd.h>

typedef struct sockaddr_un DBusSocketAddress;

/* Receive one part of a single frame. SCM_RIGHTS uses the CMSG macros and
 * an aligned variable-length control record. Return all installed handles
 * close-on-exec, including those delivered before a truncation error. Linux
 * limits one SCM_RIGHTS send to 253 descriptors. Space for 256 also accounts
 * for trailing control-record padding. */
static inline ssize_t btrcDBusReceive(int socketFd, unsigned char* data, size_t size,
                                     int* descriptors, int* received) {
    union {
        struct cmsghdr alignment;
        unsigned char bytes[CMSG_SPACE(sizeof(int) * 256)];
    } control;
    struct iovec part = {data, size};
    struct msghdr message = {0};
    message.msg_iov = &part;
    message.msg_iovlen = 1;
    message.msg_control = control.bytes;
    message.msg_controllen = sizeof(control.bytes);
    *received = 0;
    ssize_t result = recvmsg(socketFd, &message, MSG_CMSG_CLOEXEC);
    if (result < 0) { return result; }
    for (struct cmsghdr* field = CMSG_FIRSTHDR(&message); field; field = CMSG_NXTHDR(&message, field)) {
        if (field->cmsg_level == SOL_SOCKET && field->cmsg_type == SCM_RIGHTS) {
            size_t bytes = field->cmsg_len - CMSG_LEN(0);
            memcpy(descriptors + *received, CMSG_DATA(field), bytes);
            *received += (int)(bytes / sizeof(int));
        }
    }
    if (message.msg_flags & MSG_CTRUNC) {
        errno = EMSGSIZE;
        return -1;
    }
    return result;
}
