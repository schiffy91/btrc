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
#include <dlfcn.h>
#include <string.h>
#include <unistd.h>
#include "../X11Autolaunch/BtrcLinuxDBusX11Autolaunch.h"

typedef struct sockaddr_un DBusSocketAddress;

/* Linux links optional first-party X11 session-bus activation providers
 * through a versioned weak symbol (for static linking) with a POSIX dlsym
 * fallback (for LD_PRELOAD into non-PIE executables). It is null for
 * standalone DBus programs. A statically linked package or an adapter
 * selected by the ELF loader stays resident for the lifetime of the process. */
extern const BtrcLinuxDBusX11AutolaunchV1* btrcLinuxDBusX11AutolaunchV1(void) __attribute__((weak));

static inline const BtrcLinuxDBusX11AutolaunchV1* btrcResolveDBusX11Autolaunch(void) {
    if (btrcLinuxDBusX11AutolaunchV1) { return btrcLinuxDBusX11AutolaunchV1(); }
    void* process = dlopen(NULL, RTLD_LAZY);
    if (!process) { return NULL; }
    void* symbol = dlsym(process, "btrcLinuxDBusX11AutolaunchV1");
    dlclose(process);
    if (!symbol) { return NULL; }
    typedef const BtrcLinuxDBusX11AutolaunchV1* (*ProviderEntry)(void);
    ProviderEntry entry = NULL;
    memcpy(&entry, &symbol, sizeof(entry));
    return entry();
}

static inline size_t btrcDBusLaunchSession(const char* machineId, char* output, size_t capacity) {
    const BtrcLinuxDBusX11AutolaunchV1* provider = btrcResolveDBusX11Autolaunch();
    if (!provider || !provider->launch || !machineId || !output || capacity <= 1) { return 0; }
    size_t length = provider->launch(machineId, output, capacity);
    if (length == 0 || length >= capacity) { return 0; }
    output[length] = '\0';
    return length;
}

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
