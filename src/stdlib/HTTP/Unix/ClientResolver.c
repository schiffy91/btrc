/* getaddrinfo has no portable deadline. A worker owns the lookup until
 * libc returns. The caller can leave on timeout without joining it or
 * leaving its own storage in use. Saturated callers wait on the same
 * monotonic deadline, bounding the number of outstanding resolver threads. */
#include "ClientSockets.h"
#include <arpa/inet.h>
#include <pthread.h>
#include <stdlib.h>
#include <time.h>

struct HttpLookup {
    char host[256];
    char service[16];
    struct addrinfo *addresses;
    int completed;
    int abandoned;
};

static pthread_mutex_t resolverLock = PTHREAD_MUTEX_INITIALIZER;
static pthread_once_t resolverOnce = PTHREAD_ONCE_INIT;
static pthread_cond_t resolverChanged;
static int resolverInitError;
static unsigned int activeLookups;
enum { maxLookups = 32 };

static void initResolver(void) {
#if defined(__APPLE__)
    resolverInitError = pthread_cond_init(&resolverChanged, NULL);
#else
    pthread_condattr_t attributes;
    resolverInitError = pthread_condattr_init(&attributes);
    if (resolverInitError != 0) { return; }
    resolverInitError = pthread_condattr_setclock(&attributes, CLOCK_MONOTONIC);
    if (resolverInitError == 0) {
        resolverInitError = pthread_cond_init(&resolverChanged, &attributes);
    }
    pthread_condattr_destroy(&attributes);
#endif
}

static int waitUntil(const struct timespec *deadline) {
#if defined(__APPLE__)
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) { return errno; }
    struct timespec left = {deadline->tv_sec - now.tv_sec, deadline->tv_nsec - now.tv_nsec};
    if (left.tv_nsec < 0) { left.tv_sec--; left.tv_nsec += 1000000000L; }
    if (left.tv_sec < 0) { return ETIMEDOUT; }
    return pthread_cond_timedwait_relative_np(&resolverChanged, &resolverLock, &left);
#else
    return pthread_cond_timedwait(&resolverChanged, &resolverLock, deadline);
#endif
}

static void *resolveHost(void *context) {
    struct HttpLookup *lookup = context;
    struct addrinfo hints = {0};
    struct addrinfo *addresses = NULL;
    hints.ai_family = AF_UNSPEC;
    hints.ai_socktype = SOCK_STREAM;
    hints.ai_flags = AI_NUMERICSERV;
    int status = getaddrinfo(lookup->host, lookup->service, &hints, &addresses);
    pthread_mutex_lock(&resolverLock);
    activeLookups--;
    if (lookup->abandoned) {
        if (status == 0) { freeaddrinfo(addresses); }
        free(lookup);
    } else {
        lookup->addresses = status == 0 ? addresses : NULL;
        lookup->completed = 1;
    }
    pthread_cond_broadcast(&resolverChanged);
    pthread_mutex_unlock(&resolverLock);
    return NULL;
}

int btrcHttpResolve(char *host, char *service, long long deadlineMs, void **result) {
    *result = NULL;
    if (deadlineMs <= 0) { return -1; }
    const struct timespec deadline = {(time_t)(deadlineMs / 1000), (long)(deadlineMs % 1000) * 1000000L};
    struct HttpLookup *lookup = calloc(1, sizeof(*lookup));
    if (lookup == NULL) { return -2; }
    if (strlen(host) >= sizeof(lookup->host) || strlen(service) >= sizeof(lookup->service)) {
        free(lookup);
        return -2;
    }
    strcpy(lookup->host, host);
    strcpy(lookup->service, service);
    pthread_once(&resolverOnce, initResolver);
    if (resolverInitError != 0) { free(lookup); return -2; }
    pthread_mutex_lock(&resolverLock);
    int status = 0;
    while (activeLookups >= maxLookups && status == 0) { status = waitUntil(&deadline); }
    pthread_attr_t attributes;
    if (status == 0) {
        status = pthread_attr_init(&attributes);
        if (status == 0) {
            pthread_t worker;
            status = pthread_attr_setdetachstate(&attributes, PTHREAD_CREATE_DETACHED);
            if (status == 0) { status = pthread_create(&worker, &attributes, resolveHost, lookup); }
            pthread_attr_destroy(&attributes);
        }
    }
    if (status != 0) {
        pthread_mutex_unlock(&resolverLock);
        free(lookup);
        return status == ETIMEDOUT ? -1 : -2;
    }
    activeLookups++;
    while (!lookup->completed && status == 0) { status = waitUntil(&deadline); }
    if (!lookup->completed) {
        lookup->abandoned = 1;
        pthread_mutex_unlock(&resolverLock);
        return status == ETIMEDOUT ? -1 : -2;
    }
    *result = lookup->addresses;
    pthread_mutex_unlock(&resolverLock);
    free(lookup);
    return *result == NULL ? -2 : 0;
}

/* Advance even when socket creation fails so the caller can try the next
 * candidate. The address remains owned by the head of the resolver list. */
int btrcHttpAddressSocket(void **cursor, struct sockaddr **address, socklen_t *length) {
    const struct addrinfo *entry = *cursor;
    *cursor = entry->ai_next;
    *address = entry->ai_addr;
    *length = entry->ai_addrlen;
    return socket(entry->ai_family, entry->ai_socktype, entry->ai_protocol);
}

void btrcHttpFreeAddresses(void *addresses) {
    freeaddrinfo(addresses);
}

/* SOCKS4 requires IPv4. SOCKS5h forwards an unresolved hostname verbatim.
 * The local modes share the normal transport's bounded resolver worker. */
int btrcHttpSocksAddress(char *host, int local, int onlyIPv4, long long deadline, char *output) {
    if (inet_pton(AF_INET, host, output) == 1) return 4;
    if (inet_pton(AF_INET6, host, output) == 1) return onlyIPv4 ? -2 : 16;
    if (!local) return 0;
    void *found = NULL;
    int status = btrcHttpResolve(host, "0", deadline, &found);
    if (status != 0) return status;
    int size = -2;
    for (struct addrinfo *p = found; p; p = p->ai_next) {
        if (p->ai_family == AF_INET) {
            memcpy(output, &((struct sockaddr_in *)p->ai_addr)->sin_addr, 4);
            size = 4;
            break;
        }
        if (!onlyIPv4 && p->ai_family == AF_INET6) {
            memcpy(output, &((struct sockaddr_in6 *)p->ai_addr)->sin6_addr, 16);
            size = 16;
            break;
        }
    }
    btrcHttpFreeAddresses(found);
    return size;
}
