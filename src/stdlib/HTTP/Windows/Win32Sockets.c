/* Winsock primitives behind Library.HTTP's HTTPSocket on windows rows.
 *
 * The package native plan compiles this separate C11 unit for programs that
 * reach HTTPSocket on a Windows row and links it against the SDK's ws2_32.
 * The Windows twin of HTTPSocket (HTTPSocket.btrc, `#if defined(_WIN32)`)
 * decides policy -- deadlines, request framing and limits -- and calls these
 * functions through extern declarations. Each operation does one native step
 * and returns BTRC_WIN_SOCKET_DONE, BTRC_WIN_SOCKET_WOULD_BLOCK or
 * BTRC_WIN_SOCKET_FAILED; a failure captures WSAGetLastError before any
 * cleanup can overwrite it and leaves the matching POSIX value in errno
 * (WSAEADDRINUSE is EADDRINUSE, WSAECONNRESET is ECONNRESET, ...), so a caller
 * reads the same errno and strerror(errno) it reads on the POSIX rows.
 *
 * A SOCKET is pointer-width, so it never crosses into btrc and is never
 * truncated into HTTPSocket's int descriptors. The registry below owns every
 * SOCKET the provider opens and hands out a token: generation * 1024 + slot,
 * always at least 1024 and below 2^30. A closed token never resolves again:
 * a slot's next tenant gets the next generation, and a slot whose last
 * generation has been used is retired rather than wrapped. Admission fails
 * with EMFILE when no slot is free.
 *
 * Each SOCKET is nonblocking, owns its own network event (WSAEventSelect) and a
 * cancel event, and is never inheritable (WSA_FLAG_NO_HANDLE_INHERIT; an
 * accepted socket is checked and cleared). An operation borrows its slot
 * while it uses the SOCKET. Close invalidates the token at once and sets the
 * cancel event, which wakes every wait on it; the SOCKET and both events are
 * closed exactly once, by close itself or by the last borrower to give the
 * slot back, so a waiter that close woke never uses a closed SOCKET. Waits
 * collect what WSAEnumNetworkEvents reports into the slot's pending set, so
 * a wait never discards readiness another wait on the same SOCKET needs;
 * FD_CLOSE stays pending once seen, as POLLHUP does.
 *
 * WSAStartup(2.2) runs when the first SOCKET is admitted and WSACleanup when
 * the last borrower releases the last closed socket. This separate native
 * unit uses the SDK's Winsock declarations; the package plan links ws2_32.
 * The BTRC provider owns the registry root shared by every generated unit. */
#ifndef BTRC_STDLIB_WIN32_SOCKETS_C
#define BTRC_STDLIB_WIN32_SOCKETS_C

#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include "Win32Sockets.h"
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* What every operation reports. */
#define BTRC_WIN_SOCKET_DONE 0
#define BTRC_WIN_SOCKET_WOULD_BLOCK 1
#define BTRC_WIN_SOCKET_FAILED (-1)

/* What a wait is for: HTTPSocket.waitFor's events, the values POLLIN and
 * POLLOUT have on every POSIX row. Readable is a pending accept on a listener. */
#define BTRC_WIN_SOCKET_READABLE 1
#define BTRC_WIN_SOCKET_WRITABLE 4

/* Tokens. */
#define BTRC_WIN_SOCKET_SLOT_BITS 10
#define BTRC_WIN_SOCKET_SLOTS (1 << BTRC_WIN_SOCKET_SLOT_BITS)
#define BTRC_WIN_SOCKET_LAST_GENERATION ((1 << 20) - 1)

/* Slot states. */
#define BTRC_WIN_SOCKET_FREE 0
#define BTRC_WIN_SOCKET_OPEN 1
#define BTRC_WIN_SOCKET_CLOSING 2
#define BTRC_WIN_SOCKET_RETIRED 3

typedef struct {
    SOCKET socket;
    HANDLE network;
    HANDLE cancel;
    /* The token's generation; 0 before the slot's first tenant. */
    int generation;
    int state;
    int listener;
    /* Operations using `socket` outside the registry lock. */
    int borrowers;
    /* FD_ bits WSAEnumNetworkEvents reported that no wait has taken yet. */
    long pending;
} BtrcWinSocketSlot;

typedef struct {
    SRWLOCK lock;
    /* WSAStartup holds while `live` is positive. */
    int started;
    int live;
    /* Successful WSAStartup calls and their WSACleanup calls, for the tests. */
    int startups;
    int cleanups;
    int cursor;
    BtrcWinSocketSlot slots[BTRC_WIN_SOCKET_SLOTS];
} BtrcWinSocketRegistry;

/* The POSIX errno a Winsock (or Win32) error means. */
static inline int btrcWinSocketErrno(int error) {
    switch (error) {
        case WSAEINTR: return EINTR;
        case WSAEBADF: return EBADF;
        case WSAEACCES: return EACCES;
        case WSAEFAULT: return EFAULT;
        case WSAEINVAL: return EINVAL;
        case WSAEMFILE: return EMFILE;
        case WSAEWOULDBLOCK: return EWOULDBLOCK;
        case WSAEINPROGRESS: return EINPROGRESS;
        case WSAEALREADY: return EALREADY;
        case WSAENOTSOCK: return ENOTSOCK;
        case WSAEDESTADDRREQ: return EDESTADDRREQ;
        case WSAEMSGSIZE: return EMSGSIZE;
        case WSAEPROTOTYPE: return EPROTOTYPE;
        case WSAENOPROTOOPT: return ENOPROTOOPT;
        case WSAEPROTONOSUPPORT: return EPROTONOSUPPORT;
        case WSAEOPNOTSUPP: return EOPNOTSUPP;
        case WSAEAFNOSUPPORT: return EAFNOSUPPORT;
        case WSAEADDRINUSE: return EADDRINUSE;
        case WSAEADDRNOTAVAIL: return EADDRNOTAVAIL;
        case WSAENETDOWN: return ENETDOWN;
        case WSAENETUNREACH: return ENETUNREACH;
        case WSAENETRESET: return ENETRESET;
        case WSAECONNABORTED: return ECONNABORTED;
        case WSAECONNRESET: return ECONNRESET;
        case WSAENOBUFS: return ENOBUFS;
        case WSAEISCONN: return EISCONN;
        case WSAENOTCONN: return ENOTCONN;
        /* A send after shutdown(SD_SEND) is POSIX's EPIPE. */
        case WSAESHUTDOWN: return EPIPE;
        case WSAETIMEDOUT: return ETIMEDOUT;
        case WSAECONNREFUSED: return ECONNREFUSED;
        case WSAEHOSTUNREACH: return EHOSTUNREACH;
        case WSAEPROCLIM: return EAGAIN;
        case WSASYSNOTREADY:
        case WSAVERNOTSUPPORTED:
        case WSANOTINITIALISED: return ENETDOWN;
        case ERROR_ACCESS_DENIED: return EACCES;
        case ERROR_INVALID_HANDLE: return EBADF;
        case ERROR_INVALID_PARAMETER: return EINVAL;
        case ERROR_NOT_ENOUGH_MEMORY:
        case ERROR_OUTOFMEMORY: return ENOMEM;
        case ERROR_MOD_NOT_FOUND:
        case ERROR_PROC_NOT_FOUND: return ENOSYS;
        default: return EIO;
    }
}

static inline int btrcWinSocketFail(int error) {
    errno = btrcWinSocketErrno(error);
    return BTRC_WIN_SOCKET_FAILED;
}

/* The registry `root` names, created on first use and kept for the life of
 * the process, so a retired generation is never handed out again. */
static inline BtrcWinSocketRegistry* btrcWinSocketRegistry(void** root) {
    BtrcWinSocketRegistry* registry = (BtrcWinSocketRegistry*)InterlockedCompareExchangePointer((PVOID volatile*)root, NULL, NULL);
    if (registry != NULL) { return registry; }
    BtrcWinSocketRegistry* created = (BtrcWinSocketRegistry*)calloc(1, sizeof(BtrcWinSocketRegistry));
    if (created == NULL) { return NULL; }
    InitializeSRWLock(&created->lock);
    for (int index = 0; index < BTRC_WIN_SOCKET_SLOTS; index++) { created->slots[index].socket = INVALID_SOCKET; }
    registry = (BtrcWinSocketRegistry*)InterlockedCompareExchangePointer((PVOID volatile*)root, created, NULL);
    if (registry != NULL) {
        free(created);
        return registry;
    }
    return created;
}

/* Holds WSAStartup for the socket about to be admitted. The caller holds the
 * lock; 0 or the error WSAStartup returned. */
static inline int btrcWinSocketBegin(BtrcWinSocketRegistry* registry) {
    if (registry->started) { return 0; }
    WSADATA data;
    memset(&data, 0, sizeof(data));
    int status = WSAStartup(MAKEWORD(2, 2), &data);
    if (status != 0) { return status; }
    registry->started = 1;
    registry->startups++;
    return 0;
}

/* Releases WSAStartup once no socket is left. The caller holds the lock. */
static inline void btrcWinSocketEnd(BtrcWinSocketRegistry* registry) {
    if (registry->live == 0 && registry->started) {
        WSACleanup();
        registry->started = 0;
        registry->cleanups++;
    }
}

/* A SOCKET the caller owns but has not admitted, with its events. */
static inline void btrcWinSocketDiscard(SOCKET socket, HANDLE network, HANDLE cancel) {
    if (socket != INVALID_SOCKET) { closesocket(socket); }
    if (network != NULL) { CloseHandle(network); }
    if (cancel != NULL) { CloseHandle(cancel); }
}

/* Gives `socket` a slot and returns its token, or -1 when every slot is
 * taken or retired. The caller holds the lock. */
static inline int btrcWinSocketAdmit(BtrcWinSocketRegistry* registry, SOCKET socket, HANDLE network, HANDLE cancel, int listener) {
    for (int step = 0; step < BTRC_WIN_SOCKET_SLOTS; step++) {
        int index = (registry->cursor + step) % BTRC_WIN_SOCKET_SLOTS;
        BtrcWinSocketSlot* slot = &registry->slots[index];
        if (slot->state != BTRC_WIN_SOCKET_FREE) { continue; }
        registry->cursor = (index + 1) % BTRC_WIN_SOCKET_SLOTS;
        slot->generation++;
        slot->socket = socket;
        slot->network = network;
        slot->cancel = cancel;
        slot->state = BTRC_WIN_SOCKET_OPEN;
        slot->listener = listener;
        slot->borrowers = 0;
        slot->pending = 0;
        registry->live++;
        return (slot->generation << BTRC_WIN_SOCKET_SLOT_BITS) | index;
    }
    return -1;
}

/* The open slot `token` names, or NULL. The caller holds the lock. */
static inline BtrcWinSocketSlot* btrcWinSocketLookup(BtrcWinSocketRegistry* registry, int token) {
    if (token < BTRC_WIN_SOCKET_SLOTS) { return NULL; }
    BtrcWinSocketSlot* slot = &registry->slots[token & (BTRC_WIN_SOCKET_SLOTS - 1)];
    if (slot->state != BTRC_WIN_SOCKET_OPEN || slot->generation != (token >> BTRC_WIN_SOCKET_SLOT_BITS)) { return NULL; }
    return slot;
}

/* Closes a slot no borrower holds: its SOCKET and events exactly once. The
 * caller holds the lock. */
static inline void btrcWinSocketFinish(BtrcWinSocketRegistry* registry, BtrcWinSocketSlot* slot) {
    btrcWinSocketDiscard(slot->socket, slot->network, slot->cancel);
    slot->socket = INVALID_SOCKET;
    slot->network = NULL;
    slot->cancel = NULL;
    slot->borrowers = 0;
    slot->pending = 0;
    slot->state = slot->generation >= BTRC_WIN_SOCKET_LAST_GENERATION ? BTRC_WIN_SOCKET_RETIRED : BTRC_WIN_SOCKET_FREE;
    registry->live--;
    btrcWinSocketEnd(registry);
}

/* Borrows the slot `token` names: its SOCKET stays open until the matching
 * btrcWinSocketGiveBack. NULL (errno EBADF) for a closed or unknown token. */
static inline BtrcWinSocketSlot* btrcWinSocketBorrow(void** root, int token, BtrcWinSocketRegistry** owner) {
    BtrcWinSocketRegistry* registry = btrcWinSocketRegistry(root);
    *owner = registry;
    if (registry == NULL) {
        errno = ENOMEM;
        return NULL;
    }
    AcquireSRWLockExclusive(&registry->lock);
    BtrcWinSocketSlot* slot = btrcWinSocketLookup(registry, token);
    if (slot != NULL) { slot->borrowers++; }
    ReleaseSRWLockExclusive(&registry->lock);
    if (slot == NULL) { errno = EBADF; }
    return slot;
}

static inline void btrcWinSocketGiveBack(BtrcWinSocketRegistry* registry, BtrcWinSocketSlot* slot) {
    AcquireSRWLockExclusive(&registry->lock);
    slot->borrowers--;
    if (slot->state == BTRC_WIN_SOCKET_CLOSING && slot->borrowers == 0) { btrcWinSocketFinish(registry, slot); }
    ReleaseSRWLockExclusive(&registry->lock);
}

/* A nonblocking, non-inheritable IPv4 listener on 127.0.0.1 (or every
 * interface when `bindAny`) and `port` (0 picks one), with
 * SO_EXCLUSIVEADDRUSE set before bind, so no other socket can take the port
 * while it listens. */
int btrcWinSocketListen(void** root, int port, int bindAny, int backlog, int* token) {
    *token = -1;
    if (port < 0 || port > 65535 || backlog < 1) {
        errno = EINVAL;
        return BTRC_WIN_SOCKET_FAILED;
    }
    BtrcWinSocketRegistry* registry = btrcWinSocketRegistry(root);
    if (registry == NULL) {
        errno = ENOMEM;
        return BTRC_WIN_SOCKET_FAILED;
    }
    AcquireSRWLockExclusive(&registry->lock);
    int status = btrcWinSocketBegin(registry);
    if (status != 0) {
        ReleaseSRWLockExclusive(&registry->lock);
        return btrcWinSocketFail(status);
    }
    HANDLE network = NULL;
    HANDLE cancel = NULL;
    int error = 0;
    SOCKET socket = WSASocketW(AF_INET, SOCK_STREAM, IPPROTO_TCP, NULL, 0, WSA_FLAG_NO_HANDLE_INHERIT);
    if (socket == INVALID_SOCKET) { error = WSAGetLastError(); }
    int exclusive = 1;
    if (error == 0 && setsockopt(socket, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, (const char*)&exclusive, (int)sizeof(exclusive)) == SOCKET_ERROR) {
        error = WSAGetLastError();
    }
    if (error == 0) {
        struct sockaddr_in address;
        memset(&address, 0, sizeof(address));
        address.sin_family = AF_INET;
        address.sin_port = htons((unsigned short)port);
        address.sin_addr.s_addr = htonl(bindAny ? INADDR_ANY : INADDR_LOOPBACK);
        if (bind(socket, (const struct sockaddr*)&address, (int)sizeof(address)) == SOCKET_ERROR || listen(socket, backlog) == SOCKET_ERROR) {
            error = WSAGetLastError();
        }
    }
    if (error == 0) {
        network = CreateEventW(NULL, TRUE, FALSE, NULL);
        if (network == NULL) { error = (int)GetLastError(); }
        if (error == 0) {
            cancel = CreateEventW(NULL, TRUE, FALSE, NULL);
            if (cancel == NULL) { error = (int)GetLastError(); }
        }
        if (error == 0 && (WSAEventSelect(socket, network, FD_ACCEPT) == SOCKET_ERROR)) {
            error = WSAGetLastError();
        }
    }
    if (error == 0) {
        *token = btrcWinSocketAdmit(registry, socket, network, cancel, 1);
        if (*token < 0) { error = WSAEMFILE; }
    }
    if (error != 0) {
        btrcWinSocketDiscard(socket, network, cancel);
        btrcWinSocketEnd(registry);
        ReleaseSRWLockExclusive(&registry->lock);
        return btrcWinSocketFail(error);
    }
    ReleaseSRWLockExclusive(&registry->lock);
    return BTRC_WIN_SOCKET_DONE;
}

/* The next pending connection of `listener` as a token, or WOULD_BLOCK when
 * none is waiting. The new SOCKET leaves the listener's event at once for one
 * of its own (FD_READ, FD_WRITE, FD_CLOSE), before anything can wait on it. */
int btrcWinSocketAccept(void** root, int listener, int* token) {
    *token = -1;
    BtrcWinSocketRegistry* registry = NULL;
    BtrcWinSocketSlot* slot = btrcWinSocketBorrow(root, listener, &registry);
    if (slot == NULL) { return BTRC_WIN_SOCKET_FAILED; }
    if (!slot->listener) {
        btrcWinSocketGiveBack(registry, slot);
        errno = EINVAL;
        return BTRC_WIN_SOCKET_FAILED;
    }
    SOCKET socket = accept(slot->socket, NULL, NULL);
    if (socket == INVALID_SOCKET) {
        int error = WSAGetLastError();
        btrcWinSocketGiveBack(registry, slot);
        /* WSAECONNRESET: the peer gave up before this accept; take the next. */
        if (error == WSAEWOULDBLOCK || error == WSAEINTR || error == WSAECONNRESET) { return BTRC_WIN_SOCKET_WOULD_BLOCK; }
        return btrcWinSocketFail(error);
    }
    /* The listener was opened with WSA_FLAG_NO_HANDLE_INHERIT; make sure its
     * connection is not inheritable either. */
    int error = 0;
    DWORD flags = 0;
    if (!GetHandleInformation((HANDLE)socket, &flags)) {
        error = (int)GetLastError();
    } else if ((flags & HANDLE_FLAG_INHERIT) != 0 && !SetHandleInformation((HANDLE)socket, HANDLE_FLAG_INHERIT, 0)) {
        error = (int)GetLastError();
    }
    HANDLE network = NULL;
    HANDLE cancel = NULL;
    if (error == 0) {
        network = CreateEventW(NULL, TRUE, FALSE, NULL);
        if (network == NULL) { error = (int)GetLastError(); }
        if (error == 0) {
            cancel = CreateEventW(NULL, TRUE, FALSE, NULL);
            if (cancel == NULL) { error = (int)GetLastError(); }
        }
        if (error == 0 && (WSAEventSelect(socket, network, FD_READ | FD_WRITE | FD_CLOSE) == SOCKET_ERROR)) {
            error = WSAGetLastError();
        }
    }
    AcquireSRWLockExclusive(&registry->lock);
    if (error == 0) {
        *token = btrcWinSocketAdmit(registry, socket, network, cancel, 0);
        if (*token < 0) { error = WSAEMFILE; }
    }
    if (error != 0) { btrcWinSocketDiscard(socket, network, cancel); }
    ReleaseSRWLockExclusive(&registry->lock);
    btrcWinSocketGiveBack(registry, slot);
    return error == 0 ? BTRC_WIN_SOCKET_DONE : btrcWinSocketFail(error);
}

/* Waits up to `milliseconds` for `events` (READABLE, WRITABLE or both) on
 * `token`: 1 when one is ready (FD_CLOSE counts for both), 0 when the time
 * ran out, -1 when the token is closed, or closed during the wait (errno
 * ECANCELED). */
int btrcWinSocketWait(void** root, int token, int events, int milliseconds) {
    BtrcWinSocketRegistry* registry = NULL;
    BtrcWinSocketSlot* slot = btrcWinSocketBorrow(root, token, &registry);
    if (slot == NULL) { return -1; }
    long wanted = FD_CLOSE;
    if ((events & BTRC_WIN_SOCKET_READABLE) != 0) { wanted |= slot->listener ? FD_ACCEPT : FD_READ; }
    if ((events & BTRC_WIN_SOCKET_WRITABLE) != 0) { wanted |= FD_WRITE; }
    ULONGLONG deadline = GetTickCount64() + (ULONGLONG)(milliseconds > 0 ? milliseconds : 0);
    int result = 0;
    while (1) {
        AcquireSRWLockExclusive(&registry->lock);
        long ready = slot->pending & wanted;
        slot->pending &= ~(ready & ~(long)FD_CLOSE);
        int closing = slot->state != BTRC_WIN_SOCKET_OPEN;
        ReleaseSRWLockExclusive(&registry->lock);
        if (closing) {
            errno = ECANCELED;
            result = -1;
            break;
        }
        if (ready != 0) {
            result = 1;
            break;
        }
        ULONGLONG now = GetTickCount64();
        if (now >= deadline) { break; }
        ULONGLONG left = deadline - now;
        HANDLE handles[2] = { slot->network, slot->cancel };
        DWORD signaled = WaitForMultipleObjects(2, handles, FALSE, left > (ULONGLONG)0x7fffffff ? (DWORD)0x7fffffff : (DWORD)left);
        if (signaled == WAIT_TIMEOUT) { continue; }
        if (signaled == WAIT_OBJECT_0 + 1) { continue; }
        if (signaled != WAIT_OBJECT_0) {
            errno = btrcWinSocketErrno((int)GetLastError());
            result = -1;
            break;
        }
        WSANETWORKEVENTS happened;
        memset(&happened, 0, sizeof(happened));
        AcquireSRWLockExclusive(&registry->lock);
        int status = WSAEnumNetworkEvents(slot->socket, slot->network, &happened);
        int error = status == SOCKET_ERROR ? WSAGetLastError() : 0;
        if (status != SOCKET_ERROR) { slot->pending |= happened.lNetworkEvents; }
        ReleaseSRWLockExclusive(&registry->lock);
        if (status == SOCKET_ERROR) {
            errno = btrcWinSocketErrno(error);
            result = -1;
            break;
        }
    }
    btrcWinSocketGiveBack(registry, slot);
    return result;
}

/* Up to `capacity` bytes into `buffer`; *received 0 means the peer closed. */
int btrcWinSocketReceive(void** root, int token, char* buffer, int capacity, int* received) {
    *received = 0;
    if (buffer == NULL || capacity <= 0) {
        errno = EINVAL;
        return BTRC_WIN_SOCKET_FAILED;
    }
    BtrcWinSocketRegistry* registry = NULL;
    BtrcWinSocketSlot* slot = btrcWinSocketBorrow(root, token, &registry);
    if (slot == NULL) { return BTRC_WIN_SOCKET_FAILED; }
    int count = slot->listener ? SOCKET_ERROR : recv(slot->socket, buffer, capacity, 0);
    int error = count == SOCKET_ERROR ? (slot->listener ? WSAENOTCONN : WSAGetLastError()) : 0;
    btrcWinSocketGiveBack(registry, slot);
    if (count >= 0) {
        *received = count;
        return BTRC_WIN_SOCKET_DONE;
    }
    if (error == WSAEWOULDBLOCK || error == WSAEINTR) { return BTRC_WIN_SOCKET_WOULD_BLOCK; }
    return btrcWinSocketFail(error);
}

/* Up to `length` bytes of `data`; *sent is how many the transport took. */
int btrcWinSocketSend(void** root, int token, char* data, int length, int* sent) {
    *sent = 0;
    if (data == NULL || length <= 0) {
        errno = EINVAL;
        return BTRC_WIN_SOCKET_FAILED;
    }
    BtrcWinSocketRegistry* registry = NULL;
    BtrcWinSocketSlot* slot = btrcWinSocketBorrow(root, token, &registry);
    if (slot == NULL) { return BTRC_WIN_SOCKET_FAILED; }
    int count = slot->listener ? SOCKET_ERROR : send(slot->socket, data, length, 0);
    int error = count == SOCKET_ERROR ? (slot->listener ? WSAENOTCONN : WSAGetLastError()) : 0;
    btrcWinSocketGiveBack(registry, slot);
    if (count >= 0) {
        *sent = count;
        return BTRC_WIN_SOCKET_DONE;
    }
    if (error == WSAEWOULDBLOCK || error == WSAEINTR) { return BTRC_WIN_SOCKET_WOULD_BLOCK; }
    return btrcWinSocketFail(error);
}

/* shutdown(SD_SEND): the peer reads EOF after everything already sent. */
int btrcWinSocketShutdownSend(void** root, int token) {
    BtrcWinSocketRegistry* registry = NULL;
    BtrcWinSocketSlot* slot = btrcWinSocketBorrow(root, token, &registry);
    if (slot == NULL) { return BTRC_WIN_SOCKET_FAILED; }
    int status = shutdown(slot->socket, SD_SEND);
    int error = status == SOCKET_ERROR ? WSAGetLastError() : 0;
    btrcWinSocketGiveBack(registry, slot);
    return error == 0 ? BTRC_WIN_SOCKET_DONE : btrcWinSocketFail(error);
}

/* Invalidates `token` and wakes its waiters; the SOCKET closes once no
 * operation holds it. A second close of one token fails with EBADF. */
int btrcWinSocketClose(void** root, int token) {
    BtrcWinSocketRegistry* registry = btrcWinSocketRegistry(root);
    if (registry == NULL) {
        errno = ENOMEM;
        return BTRC_WIN_SOCKET_FAILED;
    }
    AcquireSRWLockExclusive(&registry->lock);
    BtrcWinSocketSlot* slot = btrcWinSocketLookup(registry, token);
    if (slot != NULL) {
        slot->state = BTRC_WIN_SOCKET_CLOSING;
        SetEvent(slot->cancel);
        if (slot->borrowers == 0) { btrcWinSocketFinish(registry, slot); }
    }
    ReleaseSRWLockExclusive(&registry->lock);
    if (slot == NULL) {
        errno = EBADF;
        return BTRC_WIN_SOCKET_FAILED;
    }
    return BTRC_WIN_SOCKET_DONE;
}

/* The local port `token` is bound to, or -1. */
int btrcWinSocketLocalPort(void** root, int token) {
    BtrcWinSocketRegistry* registry = NULL;
    BtrcWinSocketSlot* slot = btrcWinSocketBorrow(root, token, &registry);
    if (slot == NULL) { return -1; }
    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    int length = (int)sizeof(address);
    int status = getsockname(slot->socket, (struct sockaddr*)&address, &length);
    int error = status == SOCKET_ERROR ? WSAGetLastError() : 0;
    btrcWinSocketGiveBack(registry, slot);
    if (error != 0) {
        btrcWinSocketFail(error);
        return -1;
    }
    return (int)ntohs(address.sin_port);
}

/* Diagnostics for the tests (WinsockDiagnostics): whether the SOCKET behind
 * `token` would be inherited by a child process (1, 0, or -1 for a closed
 * token); how many sockets are open; and how many times WSAStartup and
 * WSACleanup ran. */
int btrcWinSocketInheritable(void** root, int token) {
    BtrcWinSocketRegistry* registry = NULL;
    BtrcWinSocketSlot* slot = btrcWinSocketBorrow(root, token, &registry);
    if (slot == NULL) { return -1; }
    DWORD flags = 0;
    int known = GetHandleInformation((HANDLE)slot->socket, &flags) != 0;
    btrcWinSocketGiveBack(registry, slot);
    if (!known) { return -1; }
    return (flags & HANDLE_FLAG_INHERIT) != 0 ? 1 : 0;
}

int btrcWinSocketLive(void** root) {
    BtrcWinSocketRegistry* registry = btrcWinSocketRegistry(root);
    if (registry == NULL) { return -1; }
    AcquireSRWLockExclusive(&registry->lock);
    int live = registry->live;
    ReleaseSRWLockExclusive(&registry->lock);
    return live;
}

int btrcWinSocketStartups(void** root) {
    BtrcWinSocketRegistry* registry = btrcWinSocketRegistry(root);
    if (registry == NULL) { return -1; }
    AcquireSRWLockExclusive(&registry->lock);
    int startups = registry->startups;
    ReleaseSRWLockExclusive(&registry->lock);
    return startups;
}

int btrcWinSocketCleanups(void** root) {
    BtrcWinSocketRegistry* registry = btrcWinSocketRegistry(root);
    if (registry == NULL) { return -1; }
    AcquireSRWLockExclusive(&registry->lock);
    int cleanups = registry->cleanups;
    ReleaseSRWLockExclusive(&registry->lock);
    return cleanups;
}

#endif
